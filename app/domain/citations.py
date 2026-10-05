"""Citation extraction and verification.

A report is only trustworthy if the [S#] markers mean something. This module answers two
questions deterministically, before any model is asked for an opinion:

1. Does every cited source id actually exist in this run's observations?
2. Does the sentence's numbers appear in the cited observation's data?

Check 2 is what catches the realistic failure. A model rarely invents `[S9]` out of nothing; it
much more often attaches a real source id to a number it rounded, transposed or made up. So the
numeric claims in a sentence are extracted and matched against the actual rows.

Pure functions throughout. The LLM check in the verify node runs *after* this and only on
sentences this module could not confirm, which keeps the expensive path small.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import Observation

CITATION_PATTERN = re.compile(r"\[S(\d+)\]")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
# Matches 12, 12.5, 1,234, 45%, $1.2M and -3.4 while refusing to swallow a citation's digits.
NUMBER_PATTERN = re.compile(r"-?\$?\d[\d,]*\.?\d*\s*%?")

# A report legitimately rounds what a query returned, so matching is relative, not exact.
NUMERIC_MATCH_TOLERANCE = 0.02
# Guards against a self-referencing payload sending the flattener into unbounded recursion.
MAX_PAYLOAD_DEPTH = 6


class ClaimVerdict(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED_MISSING_SOURCE = "unsupported_missing_source"
    UNSUPPORTED_NUMBER_NOT_FOUND = "unsupported_number_not_found"
    UNCITED = "uncited"
    # The deterministic checks could not decide; the verify node asks the model.
    NEEDS_MODEL_REVIEW = "needs_model_review"


@dataclass(frozen=True, slots=True)
class Claim:
    """One factual sentence from the report and what it cites."""

    sentence: str
    source_ids: tuple[str, ...]
    verdict: ClaimVerdict = ClaimVerdict.NEEDS_MODEL_REVIEW
    reason: str = ""

    @property
    def is_supported(self) -> bool:
        return self.verdict is ClaimVerdict.SUPPORTED

    def decided(self, verdict: ClaimVerdict, reason: str = "") -> Claim:
        return Claim(
            sentence=self.sentence, source_ids=self.source_ids, verdict=verdict, reason=reason
        )


@dataclass(frozen=True, slots=True)
class VerificationReport:
    claims: tuple[Claim, ...]
    score: float
    unsupported: tuple[Claim, ...]
    missing_source_ids: frozenset[str]

    @property
    def unsupported_rate(self) -> float:
        factual = [c for c in self.claims if c.source_ids or _looks_factual(c.sentence)]
        if not factual:
            return 0.0
        return len(self.unsupported) / len(factual)


def extract_source_ids(text: str) -> tuple[str, ...]:
    """Pull citation ids from text, preserving first-appearance order without duplicates."""
    seen: dict[str, None] = {}
    for match in CITATION_PATTERN.finditer(text):
        seen.setdefault(f"S{int(match.group(1))}", None)
    return tuple(seen)


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences for per-claim checking.

    Markdown structure is stripped first: a bullet is a claim, and a heading is not.
    """
    sentences: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "|", "```", ">")):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        sentences.extend(
            part.strip() for part in SENTENCE_SPLIT_PATTERN.split(line) if part.strip()
        )
    return sentences


def verify_report(
    markdown: str, observations: dict[str, Observation], *, require_citations: bool = True
) -> VerificationReport:
    """Check every factual sentence in a report against the run's observations."""
    claims: list[Claim] = []
    missing: set[str] = set()

    for sentence in split_sentences(markdown):
        source_ids = extract_source_ids(sentence)
        claim = Claim(sentence=sentence, source_ids=source_ids)

        if not source_ids:
            factual = _looks_factual(sentence)
            if factual and require_citations:
                claims.append(
                    claim.decided(
                        ClaimVerdict.UNCITED,
                        "The sentence states a fact but cites no source.",
                    )
                )
            else:
                claims.append(claim.decided(ClaimVerdict.SUPPORTED, "No factual assertion."))
            continue

        unknown = [sid for sid in source_ids if sid not in observations]
        if unknown:
            missing.update(unknown)
            claims.append(
                claim.decided(
                    ClaimVerdict.UNSUPPORTED_MISSING_SOURCE,
                    f"Cites {', '.join(unknown)}, which this run never produced.",
                )
            )
            continue

        cited = [observations[sid] for sid in source_ids]
        claims.append(_check_numbers_against_sources(claim, cited))

    resolved = tuple(claims)
    unsupported = tuple(c for c in resolved if c.verdict not in _ACCEPTABLE_VERDICTS)
    return VerificationReport(
        claims=resolved,
        score=_score(resolved),
        unsupported=unsupported,
        missing_source_ids=frozenset(missing),
    )


_ACCEPTABLE_VERDICTS = frozenset({ClaimVerdict.SUPPORTED, ClaimVerdict.NEEDS_MODEL_REVIEW})


def _check_numbers_against_sources(claim: Claim, sources: list[Observation]) -> Claim:
    """Confirm the sentence's numbers appear in the cited evidence."""
    numbers = extract_claim_values(claim.sentence)
    if not numbers:
        # No numeric assertion to check deterministically; the model reviews the wording.
        return claim.decided(ClaimVerdict.NEEDS_MODEL_REVIEW, "No numeric claim to check.")

    haystack = " ".join(_flatten_for_matching(source) for source in sources)
    source_numbers = extract_numbers(haystack)

    # Each entry is the set of forms one written value may legitimately take, so a value counts
    # as found when any form appears. Requiring every form would fail "7.1%" against a stored
    # -0.071 and vice versa.
    unmatched = [
        forms for forms in numbers if not any(_number_present(f, source_numbers) for f in forms)
    ]
    if unmatched:
        shown = ", ".join(f"{forms[0]:g}" for forms in unmatched[:3])
        return claim.decided(
            ClaimVerdict.UNSUPPORTED_NUMBER_NOT_FOUND,
            f"The value(s) {shown} do not appear in {', '.join(claim.source_ids)}.",
        )
    return claim.decided(ClaimVerdict.SUPPORTED, "Every numeric claim appears in the evidence.")


def extract_claim_values(text: str) -> list[tuple[float, ...]]:
    """Pull the written values out of a sentence, each with its acceptable alternative forms.

    A percentage is returned as both 7.1 and 0.071, because a query may store either. They are
    alternatives for one written value, not two separate claims.
    """
    without_citations = CITATION_PATTERN.sub(" ", text)
    values: list[tuple[float, ...]] = []
    for raw in NUMBER_PATTERN.findall(without_citations):
        token = raw.strip()
        parsed = _parse_number(token)
        if parsed is None:
            continue
        values.append((parsed, parsed / 100) if token.endswith("%") else (parsed,))
    return values


def extract_numbers(text: str) -> list[float]:
    """Every numeric value in the text, flattened. Used to build the evidence haystack."""
    return [value for forms in extract_claim_values(text) for value in forms]


def _parse_number(token: str) -> float | None:
    cleaned = token.rstrip("%").strip().lstrip("$").replace(",", "")
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _number_present(needle: float, haystack: list[float]) -> bool:
    """Is this value present in the evidence, allowing for rounding and units?

    Magnitudes are compared, not signed values: a query returning a pct_change of -7.1 supports
    a report sentence reading "declined 7.1%", because the direction is carried by the verb.
    The consequence is that this check cannot catch a reversed direction, so "revenue grew 7.1%"
    would also pass here. Direction is what the model review in the verify node is for, and the
    limitation is recorded in docs/backlog.md.
    """
    for candidate in haystack:
        if _close(needle, candidate) or _close(abs(needle), abs(candidate)):
            return True
        # A report may express a raw count in thousands or millions: 3,480,000 written as 3.48M.
        # The comparison is normalised by the rescaled magnitude, not the original one, or any
        # small number would appear to match any large one.
        for factor in (1_000.0, 1_000_000.0):
            if _close(abs(needle), abs(candidate) / factor):
                return True
    return False


def _close(left: float, right: float) -> bool:
    if left == right:
        return True
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) / scale <= NUMERIC_MATCH_TOLERANCE


def _flatten_for_matching(observation: Observation) -> str:
    parts = [observation.summary]
    parts.append(_stringify(observation.payload))
    return " ".join(parts)


def _stringify(value: object, depth: int = 0) -> str:
    if depth > MAX_PAYLOAD_DEPTH:
        return ""
    if isinstance(value, dict):
        return " ".join(_stringify(v, depth + 1) for v in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_stringify(v, depth + 1) for v in value)
    return str(value)


def _looks_factual(sentence: str) -> bool:
    """Heuristic: a sentence asserting a number or a comparison needs a source.

    Hedged and forward-looking language is exempt, because "we should prioritise X next
    quarter" is a recommendation, not a claim about data.
    """
    lowered = sentence.lower()
    if any(h in lowered for h in _HEDGES):
        return False
    return bool(NUMBER_PATTERN.search(sentence)) or any(k in lowered for k in _FACTUAL_MARKERS)


_HEDGES = (
    "recommend",
    "should",
    "could",
    "we suggest",
    "consider",
    "next question",
    "worth investigating",
    "this report",
    "limitation",
)

_FACTUAL_MARKERS = (
    "increased",
    "decreased",
    "declined",
    "grew",
    "fell",
    "rose",
    "dropped",
    "accounted for",
    "driven by",
    "compared to",
    "versus",
    "margin",
    "revenue was",
)


def _score(claims: tuple[Claim, ...]) -> float:
    """Share of checkable claims that passed.

    Sentences awaiting model review count as passing here; the verify node recomputes the
    score once it has the model's verdicts, so this is the deterministic lower bound.
    """
    checkable = [c for c in claims if c.source_ids or c.verdict is ClaimVerdict.UNCITED]
    if not checkable:
        return 1.0
    good = sum(1 for c in checkable if c.verdict in _ACCEPTABLE_VERDICTS)
    return round(good / len(checkable), 4)


def strip_unsupported_claims(markdown: str, unsupported: tuple[Claim, ...]) -> str:
    """Remove sentences that failed verification.

    Deleting beats silently keeping them: a report that shows a verification score of 0.8 while
    still containing the bad sentence has taught the reader nothing.
    """
    if not unsupported:
        return markdown
    result = markdown
    for claim in unsupported:
        result = result.replace(claim.sentence, "")
    # Collapse the blank lines that removal leaves behind.
    return re.sub(r"\n{3,}", "\n\n", result).strip()
