"""Document ingest: chunking, injection screening and embedding.

Chunking is paragraph-aware with a character budget rather than a fixed window, because a memo's
paragraph is its unit of meaning and splitting mid-sentence produces passages that cite badly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, func, select

from app.domain.errors import NotFoundError, ValidationError
from app.domain.ports import EmbeddingPort
from app.infra.db import Database
from app.infra.models import Chunk, Document

TARGET_CHUNK_CHARS = 900
MAX_CHUNK_CHARS = 1_400
MIN_CHUNK_CHARS = 120
MAX_DOCUMENT_CHARS = 400_000

# Phrases that indicate text is trying to address the agent rather than inform it. Matching is
# deliberately conservative: a false positive only adds a UI flag, and under-flagging is the
# failure that matters. The agent's defence does not depend on this list -- tool results are
# untrusted regardless -- so this is detection for the operator, not prevention.
_INJECTION_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("instruction override", r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"),
    ("instruction override", r"disregard\s+(?:all\s+)?(?:previous|prior|the\s+above)"),
    ("fake system prompt", r"system\s+(?:notice|prompt|message)|assistant\s+instructions"),
    ("role switch", r"you\s+are\s+now\s+(?:in\s+)?(?:a\s+|an\s+)?\w+\s*mode"),
    ("destructive sql", r"\b(?:drop|truncate)\s+table\b"),
    ("destructive sql", r"\bdelete\s+from\b"),
    ("credential exfiltration", r"169\.254\.169\.254|metadata\.google\.internal"),
    ("credential exfiltration", r"security-credentials|id_rsa|\.env\b|api[_\s-]?key"),
    ("citation suppression", r"do\s+not\s+cite"),
    ("concealment", r"do\s+not\s+(?:mention|tell|reveal|disclose)\s+(?:this|that|the\s+user)"),
    ("forced assertion", r"you\s+must\s+(?:also\s+)?state"),
)

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE)) for label, pattern in _INJECTION_SIGNATURES
)


@dataclass(frozen=True, slots=True)
class InjectionScreening:
    suspicious: bool
    reasons: tuple[str, ...]

    @property
    def summary(self) -> str:
        if not self.suspicious:
            return ""
        unique = sorted(set(self.reasons))
        return "Contains text addressed to the agent: " + ", ".join(unique) + "."


def screen_for_injection(text: str) -> InjectionScreening:
    """Flag text that appears to be addressing the agent."""
    reasons = [label for label, pattern in _INJECTION_PATTERNS if pattern.search(text)]
    return InjectionScreening(suspicious=bool(reasons), reasons=tuple(reasons))


def chunk_text(text: str) -> list[tuple[str, int, int]]:
    """Split into (content, char_start, char_end) keeping paragraph boundaries where possible.

    Offsets are preserved so a citation can point at the exact span of the original document and
    the UI can show the passage in context.
    """
    if not text.strip():
        return []

    chunks: list[tuple[str, int, int]] = []
    paragraphs = _split_paragraphs(text)

    buffer: list[tuple[str, int, int]] = []
    buffer_length = 0

    def flush() -> None:
        nonlocal buffer, buffer_length
        if not buffer:
            return
        start = buffer[0][1]
        end = buffer[-1][2]
        chunks.append((text[start:end].strip(), start, end))
        buffer = []
        buffer_length = 0

    for paragraph, start, end in paragraphs:
        length = len(paragraph)
        if length > MAX_CHUNK_CHARS:
            # A single oversized paragraph is split on sentence boundaries rather than mid-word.
            flush()
            chunks.extend(_split_long_paragraph(text, start, end))
            continue
        if buffer_length + length > TARGET_CHUNK_CHARS and buffer_length >= MIN_CHUNK_CHARS:
            flush()
        buffer.append((paragraph, start, end))
        buffer_length += length

    flush()
    return [c for c in chunks if c[0]]


def _split_paragraphs(text: str) -> list[tuple[str, int, int]]:
    paragraphs: list[tuple[str, int, int]] = []
    position = 0
    for block in re.split(r"\n\s*\n", text):
        start = text.index(block, position) if block else position
        end = start + len(block)
        position = end
        if block.strip():
            paragraphs.append((block.strip(), start, end))
    return paragraphs


def _split_long_paragraph(text: str, start: int, end: int) -> list[tuple[str, int, int]]:
    pieces: list[tuple[str, int, int]] = []
    cursor = start
    for match in re.finditer(r"(?<=[.!?])\s+", text[start:end]):
        boundary = start + match.end()
        if boundary - cursor >= TARGET_CHUNK_CHARS:
            pieces.append((text[cursor:boundary].strip(), cursor, boundary))
            cursor = boundary
    if cursor < end:
        pieces.append((text[cursor:end].strip(), cursor, end))
    return pieces


class DocumentService:
    def __init__(self, database: Database, embedding: EmbeddingPort) -> None:
        self._database = database
        self._embedding = embedding

    async def ingest(
        self,
        *,
        title: str,
        content: str,
        doc_type: str = "memo",
        source: str = "upload",
        document_id: str | None = None,
    ) -> Document:
        if not content.strip():
            raise ValidationError("The document is empty.")
        if len(content) > MAX_DOCUMENT_CHARS:
            raise ValidationError(
                f"The document is {len(content):,} characters; the limit is "
                f"{MAX_DOCUMENT_CHARS:,}. Split it into sections and upload separately."
            )

        screening = screen_for_injection(content)
        pieces = chunk_text(content)
        vectors = await self._embedding.embed_documents([piece[0] for piece in pieces])

        async with self._database.session() as session:
            if document_id is not None:
                existing = await session.get(Document, document_id)
                if existing is not None:
                    # Re-ingesting replaces the chunks rather than appending, so the seed script
                    # can run twice without doubling the corpus.
                    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
                    document = existing
                    document.title = title
                    document.content = content
                    document.doc_type = doc_type
                    document.source = source
                else:
                    document = Document(
                        id=document_id,
                        title=title,
                        content=content,
                        doc_type=doc_type,
                        source=source,
                    )
                    session.add(document)
            else:
                document = Document(title=title, content=content, doc_type=doc_type, source=source)
                session.add(document)

            document.is_suspicious = screening.suspicious
            document.suspicion_reason = screening.summary
            document.chunk_count = len(pieces)
            document.status = "ready"
            await session.flush()

            for ordinal, ((piece, start, end), vector) in enumerate(
                zip(pieces, vectors, strict=True)
            ):
                session.add(
                    Chunk(
                        document_id=document.id,
                        ordinal=ordinal,
                        content=piece,
                        char_start=start,
                        char_end=end,
                        embedding=vector,
                    )
                )
            await session.flush()
            return document

    async def list_documents(self) -> list[Document]:
        async with self._database.read_session() as session:
            result = await session.scalars(select(Document).order_by(Document.title))
            return list(result.all())

    async def get(self, document_id: str) -> Document:
        async with self._database.read_session() as session:
            document = await session.get(Document, document_id)
        if document is None:
            raise NotFoundError("That document does not exist.")
        return document

    async def delete(self, document_id: str) -> None:
        async with self._database.session() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise NotFoundError("That document does not exist.")
            await session.delete(document)

    async def count_chunks(self) -> int:
        async with self._database.read_session() as session:
            return await session.scalar(select(func.count()).select_from(Chunk)) or 0
