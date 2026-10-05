"""Tests for citation verification."""

from __future__ import annotations

import pytest

from app.domain.citations import (
    ClaimVerdict,
    extract_numbers,
    extract_source_ids,
    split_sentences,
    strip_unsupported_claims,
    verify_report,
)
from app.domain.models import Observation


def observation(source_id: str, summary: str, payload: dict[str, object]) -> Observation:
    return Observation(
        source_id=source_id,
        step_index=0,
        tool_name="sql_query",
        summary=summary,
        payload=payload,
    )


@pytest.fixture
def sources() -> dict[str, Observation]:
    return {
        "S1": observation(
            "S1",
            "EMEA revenue by quarter",
            {
                "rows": [
                    {"quarter": "Q2", "revenue_usd": 4_120_000},
                    {"quarter": "Q3", "revenue_usd": 3_480_000},
                ]
            },
        ),
        "S2": observation(
            "S2",
            "EUR/USD average rate by quarter",
            {"q2_rate": 1.09, "q3_rate": 1.012, "pct_change": -7.1},
        ),
    }


def test_extracts_source_ids_in_order_without_duplicates() -> None:
    assert extract_source_ids("a [S2] b [S1] c [S2]") == ("S2", "S1")


def test_extracts_no_ids_from_plain_text() -> None:
    assert extract_source_ids("there are no citations here") == ()


def test_splits_sentences_and_drops_markdown_structure() -> None:
    markdown = "## Heading\n- First claim here.\n\nSecond claim. Third claim!\n| a | b |\n"
    sentences = split_sentences(markdown)
    assert "## Heading" not in sentences
    assert "First claim here." in sentences
    assert "Second claim." in sentences
    assert "Third claim!" in sentences


def test_percentages_match_their_decimal_form() -> None:
    # A source storing 0.071 must satisfy a report writing 7.1%.
    assert 0.071 in extract_numbers("7.1%")


def test_supported_claim_passes(sources: dict[str, Observation]) -> None:
    report = verify_report("EMEA revenue fell to $3,480,000 in Q3 [S1].", sources)
    assert report.claims[0].verdict is ClaimVerdict.SUPPORTED
    assert report.score == 1.0


def test_fabricated_number_on_a_real_source_is_caught(sources: dict[str, Observation]) -> None:
    """The realistic failure mode: a true source id attached to an invented figure."""
    report = verify_report("EMEA revenue fell to $2,100,000 in Q3 [S1].", sources)
    assert report.claims[0].verdict is ClaimVerdict.UNSUPPORTED_NUMBER_NOT_FOUND
    assert report.unsupported
    assert "2100000" in report.claims[0].reason.replace(",", "") or "2.1" in report.claims[0].reason


def test_citation_to_a_nonexistent_source_is_caught(sources: dict[str, Observation]) -> None:
    report = verify_report("EMEA lost 14 accounts [S9].", sources)
    assert report.claims[0].verdict is ClaimVerdict.UNSUPPORTED_MISSING_SOURCE
    assert report.missing_source_ids == frozenset({"S9"})


def test_uncited_factual_sentence_is_flagged(sources: dict[str, Observation]) -> None:
    report = verify_report("Revenue decreased by 15% in the period.", sources)
    assert report.claims[0].verdict is ClaimVerdict.UNCITED


def test_recommendation_without_a_citation_is_not_flagged(sources: dict[str, Observation]) -> None:
    # A recommendation is not a claim about data, so demanding a source would be noise.
    report = verify_report("We recommend hedging currency exposure next quarter.", sources)
    assert report.claims[0].verdict is ClaimVerdict.SUPPORTED
    assert not report.unsupported


def test_rounding_is_tolerated(sources: dict[str, Observation]) -> None:
    # 3.48m against a stored 3,480,000 is the same number, written for humans.
    report = verify_report("Q3 revenue was $3.48M [S1].", sources)
    assert report.claims[0].verdict is ClaimVerdict.SUPPORTED


def test_score_reflects_the_mix(sources: dict[str, Observation]) -> None:
    markdown = (
        "Revenue fell to $3,480,000 in Q3 [S1].\n"
        "The rate declined 7.1% [S2].\n"
        "Revenue fell to $999 in Q3 [S1].\n"
        "We lost 14 accounts [S9].\n"
    )
    report = verify_report(markdown, sources)
    assert report.score == pytest.approx(0.5)
    assert len(report.unsupported) == 2


def test_strip_removes_only_the_unsupported_sentences(sources: dict[str, Observation]) -> None:
    markdown = "Revenue fell to $3,480,000 in Q3 [S1]. Revenue fell to $999 in Q3 [S1]."
    report = verify_report(markdown, sources)
    cleaned = strip_unsupported_claims(markdown, report.unsupported)
    assert "$3,480,000" in cleaned
    assert "$999" not in cleaned


def test_empty_report_scores_one() -> None:
    assert verify_report("", {}).score == 1.0
