"""Offline embeddings by feature hashing.

The default provider, because it needs no model download and no network. A deployment on a
restricted network still gets working semantic search.

The honest trade: feature hashing captures lexical overlap, not meaning. "revenue fell" and
"income declined" are close under a real sentence encoder and far apart here. That is why
knowledge search fuses this with BM25 rather than relying on vectors alone, and it is recorded in
docs/backlog.md.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from itertools import pairwise

import numpy as np

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Below this, hash collisions dominate and similarity stops being meaningful.
MIN_DIMENSIONS = 64

# Words carrying no discriminating signal in this corpus. Kept deliberately short: an aggressive
# stop list would strip terms like "down" and "fell" that matter for the questions being asked.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


class HashEmbedding:
    """Deterministic feature-hashing embeddings.

    Bigrams are hashed alongside unigrams so word order carries some weight; without them
    "revenue up" and "revenue down" would be identical vectors.
    """

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions < MIN_DIMENSIONS:
            raise ValueError(
                f"A hash embedding needs at least {MIN_DIMENSIONS} dimensions to be usable."
            )
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "hash"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        tokens = [t for t in _TOKEN_PATTERN.findall(text.lower()) if t not in _STOP_WORDS]
        vector = np.zeros(self._dimensions, dtype=np.float32)
        if not tokens:
            return [float(value) for value in vector]

        for token in tokens:
            index, sign = self._bucket(token)
            vector[index] += sign

        # Bigrams at half weight: useful signal, but a unigram match should still dominate.
        for first, second in pairwise(tokens):
            index, sign = self._bucket(f"{first}_{second}")
            vector[index] += sign * 0.5

        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            return [float(value) for value in vector]
        # L2 normalised so cosine similarity reduces to a dot product.
        return [float(value) for value in vector / norm]

    def _bucket(self, token: str) -> tuple[int, float]:
        """Map a token to a bucket and a sign.

        blake2b rather than Python's hash(): hash() is randomised per process by PYTHONHASHSEED,
        which would mean embeddings written by the seed script did not match embeddings computed
        by the API in a different process.
        """
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        # The signed trick keeps collisions from only ever inflating a bucket.
        sign = 1.0 if value & 1 else -1.0
        return (value >> 1) % self._dimensions, sign


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Similarity between two already-normalised vectors.

    Renormalised anyway, because a vector loaded back from JSON may have drifted, and a stored
    vector from a different provider may never have been normalised at all.
    """
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return 0.0
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(a, b) / denominator)
