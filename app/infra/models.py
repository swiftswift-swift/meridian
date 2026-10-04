"""SQLAlchemy ORM models for product data.

Index choices are justified inline. The rule applied throughout: every column that appears in
a WHERE or ORDER BY of a query the application actually issues gets an index, and nothing else
does, because an unused index is write amplification for no gain.

IDs are string UUIDs rather than integers so the API can expose them without leaking row
counts and so the worker can mint a run id before the row exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def new_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="analyst")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_budget_preset: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard"
    )

    runs: Mapped[list[Run]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("role in ('admin','analyst','viewer')", name="ck_users_role"),
        # Login looks users up by email only; the unique constraint already provides the index.
    )


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    # The plan is stored denormalised as well as in run_steps: the UI needs the whole checklist
    # in one read on every poll, and joining five rows to render a sidebar is wasteful.
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    allowed_tools: Mapped[list[Any]] = mapped_column(JSON, default=list)
    require_web_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stopped_early_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resumed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Idempotency-Key from POST /runs. Unique per user so a retried request returns the first run.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Written by the worker every few seconds; the reaper finds stuck runs by its age.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="runs")
    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunStep.step_index"
    )
    observations: Mapped[list[Observation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # The runs list is "my runs, newest first", which this index serves as a covering scan.
        Index("ix_runs_user_created", "user_id", "created_at"),
        # The worker's startup recovery and the reaper both scan by status.
        Index("ix_runs_status_heartbeat", "status", "heartbeat_at"),
        # Idempotent POST /runs looks up (user, key) before inserting.
        UniqueConstraint("user_id", "idempotency_key", name="uq_runs_user_idempotency"),
        Index("ix_runs_share_token", "share_token", unique=True),
    )


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    intended_tools: Mapped[list[Any]] = mapped_column(JSON, default=list)
    expected_evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    note: Mapped[str] = mapped_column(Text, default="")
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps")

    __table_args__ = (
        # A step is addressed by (run, index, revision); re-planning rewrites a revision in place.
        UniqueConstraint("run_id", "step_index", "plan_revision", name="uq_run_steps_position"),
    )


class ToolCall(Base):
    """The idempotency ledger.

    This table is what makes a resumed run cheap and side-effect free. Before invoking a tool
    the worker looks for a completed row with the same `idempotency_key`; if it finds one it
    replays the recorded result instead of calling out again. The key is a hash of
    (run, step, tool, canonical arguments), so a genuinely different call still runs.
    """

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    from_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        # The uniqueness is the guarantee, not just an optimisation: two workers racing on the
        # same resumed run cannot both record the same logical call.
        UniqueConstraint("run_id", "idempotency_key", name="uq_tool_calls_idempotency"),
        # The run timeline and the per-tool health panel both read by run and by tool.
        Index("ix_tool_calls_run_created", "run_id", "created_at"),
        Index("ix_tool_calls_tool_status", "tool_name", "status"),
    )


class Observation(Base):
    """A tool result addressable by citation id (S1, S2, ...)."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(12), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    display: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trust: Mapped[str] = mapped_column(String(12), nullable=False, default="trusted")
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="observations")

    __table_args__ = (
        # Resolving a citation chip is a point lookup on (run, source_id).
        UniqueConstraint("run_id", "source_id", name="uq_observations_source"),
    )


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    charts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    limitations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    next_questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    markdown: Mapped[str] = mapped_column(Text, default="")
    verification_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verification_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unsupported_claims: Mapped[list[Any]] = mapped_column(JSON, default=list)


class ReportCitation(Base):
    """Which sentence cited which observation. Drives citation precision in evaluation."""

    __tablename__ = "report_citations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(12), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_report_citations_report", "report_id"),)


class Interrupt(Base):
    """A pause where the graph is waiting on a human.

    Persisted separately from the checkpoint so the UI can render the pending question without
    deserialising graph state, and so an interrupted run survives a restart.
    """

    __tablename__ = "interrupts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The run page asks "is anything waiting on me?" on every refresh.
        Index("ix_interrupts_run_resolved", "run_id", "resolved"),
    )


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False, default="memo")
    source: Mapped[str] = mapped_column(String(200), default="seed")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set when the ingest scan found injection-shaped text. Surfaced in the UI, not deleted,
    # because the demo needs to show that the agent ignores it rather than that it is absent.
    is_suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspicion_reason: Mapped[str] = mapped_column(Text, default="")

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Stored as a JSON array of floats. Fine at this corpus size; the trade-off is written up
    # in docs/adr/0007 and the honest limit is noted in docs/backlog.md.
    embedding: Mapped[list[Any]] = mapped_column(JSON, default=list)

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunks_position"),
        Index("ix_chunks_document", "document_id"),
    )


class UserMemory(Base):
    """A durable finding from a past run, recalled into later runs by the same user."""

    __tablename__ = "user_memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_user_memories_user", "user_id", "created_at"),)


class RunEventRecord(Base):
    """Persisted timeline events.

    The live stream comes from Pub/Sub, but a client that connects late, reloads, or opens a
    finished run needs the history. Storing events means the timeline is reconstructable
    without replaying the graph.
    """

    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        # SSE replay reads "events for this run after sequence N", in order.
        UniqueConstraint("run_id", "sequence", name="uq_run_events_sequence"),
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    suite: Mapped[str] = mapped_column(String(40), nullable=False, default="research")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    git_sha: Mapped[str] = mapped_column(String(40), default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    results: Mapped[list[EvaluationResult]] = relationship(
        back_populates="evaluation_run", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_evaluation_runs_suite_started", "suite", "started_at"),)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    evaluation_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_name: Mapped[str] = mapped_column(String(200), default="")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    key_fact_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_precision: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unsupported_claim_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    evaluation_run: Mapped[EvaluationRun] = relationship(back_populates="results")

    __table_args__ = (Index("ix_evaluation_results_run", "evaluation_run_id"),)
