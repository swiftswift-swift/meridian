"""The boundaries between this application and anything it does not own.

Every Protocol here is implemented at least twice: once against a real dependency and once
against something deterministic and offline. That is what makes the test suite able to run the
entire agent without a network or an API key, and it is why no vendor SDK is imported outside
`app/adapters/`.

These are `typing.Protocol`, not abstract base classes, so adapters do not inherit from
anything and the dependency arrow points inward from adapter to domain.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.domain.models import (
    ChatMessage,
    ChatResult,
    EmbeddingVector,
    QueuedJob,
    RunEvent,
    SearchHit,
    ToolInvocation,
    ToolOutcome,
)


@runtime_checkable
class ClockPort(Protocol):
    """Time, injected.

    Budget accounting, heartbeats and the stuck-run reaper all compare timestamps. A frozen
    clock in tests turns otherwise flaky timing assertions into exact ones.
    """

    def now(self) -> datetime:
        """Current time as an aware UTC datetime."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin, immune to wall-clock adjustment."""
        ...


@runtime_checkable
class ChatModelPort(Protocol):
    """A chat model that can request tool calls.

    Implemented by `OpenAiChatAdapter` (any OpenAI-compatible endpoint) and
    `ScriptedChatAdapter` (deterministic, offline, used by every test).
    """

    @property
    def model_name(self) -> str: ...

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """Produce one assistant turn, which may contain tool calls instead of prose."""
        ...


@runtime_checkable
class EmbeddingPort(Protocol):
    """Turns text into vectors for the semantic half of hybrid search."""

    @property
    def dimensions(self) -> int: ...

    @property
    def provider_name(self) -> str: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[EmbeddingVector]: ...

    async def embed_query(self, text: str) -> EmbeddingVector: ...


@runtime_checkable
class VectorStorePort(Protocol):
    """Nearest-neighbour lookup over document chunks."""

    async def upsert(
        self,
        ids: Sequence[str],
        vectors: Sequence[EmbeddingVector],
        metadatas: Sequence[Mapping[str, Any]],
    ) -> None: ...

    async def query(
        self, vector: EmbeddingVector, limit: int
    ) -> list[tuple[str, float]]:  # (chunk_id, distance)
        ...

    async def delete_by_document(self, document_id: str) -> None: ...


@runtime_checkable
class SearchProviderPort(Protocol):
    """Web search. Results are untrusted input and are always tainted by the caller."""

    @property
    def provider_name(self) -> str: ...

    async def search(self, query: str, *, limit: int) -> list[SearchHit]: ...


@runtime_checkable
class HttpFetchPort(Protocol):
    """Outbound HTTP for tools, with SSRF checks and a size cap applied by the adapter."""

    async def get_text(self, url: str, *, max_bytes: int) -> tuple[str, str]:
        """Return (final_url, body_text). Raises ToolError or SecurityViolationError."""
        ...

    async def get_json(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class ToolPort(Protocol):
    """One capability the agent can invoke.

    The agent never calls an adapter directly; it calls a tool, and the tool wrapper owns the
    timeout, retry policy, circuit breaker and structured error contract. A tool therefore
    never raises at the agent: it returns a `ToolOutcome` that records success or failure.
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def requires_network(self) -> bool:
        """Drives the "ask me before using web tools" approval interrupt."""
        ...

    def json_schema(self) -> Mapping[str, Any]:
        """The tool's argument schema, as sent to the model."""
        ...

    async def invoke(self, invocation: ToolInvocation) -> ToolOutcome: ...


@runtime_checkable
class QueuePort(Protocol):
    """Hand-off from the API to the worker.

    Implemented over Redis Streams with a consumer group, and in-process for single-machine
    development. Both honour at-least-once delivery, which is safe only because the tool
    ledger makes replaying a job idempotent.
    """

    async def enqueue(self, job: QueuedJob) -> str:
        """Returns the queue's message id."""
        ...

    async def reserve(self, *, consumer: str, block_ms: int) -> QueuedJob | None:
        """Claim the next job, or return None when nothing arrived within block_ms."""
        ...

    async def acknowledge(self, job: QueuedJob) -> None: ...

    async def release(self, job: QueuedJob) -> None:
        """Return a claimed job to the queue after a crash or graceful shutdown."""
        ...

    async def pending_count(self) -> int: ...


@runtime_checkable
class EventBusPort(Protocol):
    """Fans run events out to every connected SSE client, across processes.

    The worker publishes; API processes subscribe. Redis Pub/Sub in production, an in-process
    broadcast when Redis is absent, which is why the single-process dev setup still streams.
    """

    async def publish(self, run_id: str, event: RunEvent) -> None: ...

    def subscribe(self, run_id: str) -> AsyncIterator[RunEvent]: ...


@runtime_checkable
class CachePort(Protocol):
    """Tool-result cache with a TTL. Redis, or in-memory when Redis is absent."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...


@runtime_checkable
class CheckpointStorePort(Protocol):
    """Supplies the LangGraph checkpointer and reports where it is stored.

    Wrapping it keeps `langgraph.checkpoint` imports inside the adapter layer and lets the
    SQLite and PostgreSQL savers differ in setup without the graph noticing.
    """

    @property
    def backend_name(self) -> str: ...

    async def setup(self) -> None:
        """Create the checkpoint tables if they do not exist."""
        ...

    def checkpointer(self) -> Any:
        """The LangGraph saver. Typed as Any because its protocol is LangGraph's, not ours."""
        ...

    async def close(self) -> None: ...


@runtime_checkable
class RateLimiterPort(Protocol):
    """Fixed-window counters keyed by caller."""

    async def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        ...
