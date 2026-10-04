"""Domain entities.

These are Pydantic models rather than ORM rows on purpose. The database schema is an
implementation detail of `app/infra`; these types are what the agent, the services and the API
pass around, and they can be constructed in a test without a database.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

EmbeddingVector = list[float]


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    REPLANNED = "replanned"
    SKIPPED = "skipped"
    FAILED = "failed"


class InterruptKind(StrEnum):
    PLAN_APPROVAL = "plan_approval"
    CLARIFICATION = "clarification"
    WEB_TOOL_APPROVAL = "web_tool_approval"


class TrustLevel(StrEnum):
    """Whether a piece of content may influence tool arguments.

    `UNTRUSTED` marks anything that came from outside the system: web pages, search snippets
    and uploaded documents. Arguments derived from untrusted content cannot reach a
    network-capable tool without explicit user approval.
    """

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Chat model primitives --------------------------------------------------------


class ToolCallRequest(StrictModel):
    """The model asking for a tool to be run."""

    id: str
    tool_name: str
    arguments: dict[str, Any]


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCallRequest, ...] = ()
    tool_call_id: str | None = None
    # Set on tool messages so the injection guard can tell whether this text is allowed to
    # shape later tool arguments.
    trust: TrustLevel = TrustLevel.TRUSTED

    @model_validator(mode="after")
    def _tool_messages_need_an_id(self) -> Self:
        if self.role == "tool" and self.tool_call_id is None:
            raise ValueError("a tool message must carry the tool_call_id it answers")
        return self


class TokenUsage(StrictModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


class ChatResult(StrictModel):
    content: str
    tool_calls: tuple[ToolCallRequest, ...] = ()
    usage: TokenUsage = TokenUsage()
    model_name: str = ""
    finish_reason: str = "stop"

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# --- Tool primitives --------------------------------------------------------------


class ToolInvocation(StrictModel):
    """One request to run a tool, carrying the context the wrapper needs for the ledger."""

    run_id: str
    step_index: int
    tool_name: str
    arguments: dict[str, Any]
    call_id: str = ""
    # True when any argument value was derived from untrusted content.
    arguments_tainted: bool = False
    approved_by_user: bool = False


class ToolErrorKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    CIRCUIT_OPEN = "circuit_open"
    INVALID_ARGUMENTS = "invalid_arguments"
    REFUSED = "refused"
    NOT_FOUND = "not_found"
    UNEXPECTED = "unexpected"

    @property
    def is_retryable(self) -> bool:
        return self in {
            ToolErrorKind.TIMEOUT,
            ToolErrorKind.RATE_LIMITED,
            ToolErrorKind.UNAVAILABLE,
        }


class ToolFailure(StrictModel):
    """A failure the agent can read and plan around. Never a traceback."""

    kind: ToolErrorKind
    message: str
    guardrail: str | None = None
    hint: str | None = None


class ToolOutcome(StrictModel):
    """The result of a tool call, successful or not.

    `payload` is the structured result the agent reasons over; `display` is the shape the UI
    renders (a table, a passage, an excerpt). Keeping them separate stops presentation
    concerns leaking into prompts.
    """

    tool_name: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    display: dict[str, Any] = Field(default_factory=dict)
    failure: ToolFailure | None = None
    latency_ms: int = 0
    attempts: int = 1
    from_cache: bool = False
    trust: TrustLevel = TrustLevel.TRUSTED
    # Populated when a guardrail or heuristic found something worth showing the user.
    flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _failure_matches_ok(self) -> Self:
        if self.ok and self.failure is not None:
            raise ValueError("a successful outcome cannot carry a failure")
        if not self.ok and self.failure is None:
            raise ValueError("a failed outcome must explain itself with a ToolFailure")
        return self


class SearchHit(StrictModel):
    title: str
    url: str
    snippet: str
    published_at: datetime | None = None


# --- Plan, observations and budgets -----------------------------------------------


class PlanStep(StrictModel):
    index: int = Field(ge=0)
    description: str
    intended_tools: tuple[str, ...] = ()
    expected_evidence: str = ""
    status: StepStatus = StepStatus.PENDING
    note: str = ""

    def with_status(self, status: StepStatus, note: str = "") -> PlanStep:
        return self.model_copy(update={"status": status, "note": note or self.note})


class Plan(StrictModel):
    steps: tuple[PlanStep, ...] = ()
    revision: int = 0
    replan_reason: str = ""

    @property
    def next_pending_index(self) -> int | None:
        for step in self.steps:
            if step.status is StepStatus.PENDING:
                return step.index
        return None

    @property
    def is_complete(self) -> bool:
        return self.next_pending_index is None


class Observation(StrictModel):
    """One recorded tool result, addressable by a citation id such as S3.

    The report cites these ids, and the UI resolves a chip back to this record to show the
    exact SQL and rows, the document passage, or the fetched excerpt.
    """

    source_id: str
    step_index: int
    tool_name: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    display: dict[str, Any] = Field(default_factory=dict)
    trust: TrustLevel = TrustLevel.TRUSTED
    flags: tuple[str, ...] = ()
    created_at: datetime | None = None


class Budget(StrictModel):
    """Hard caps for one run. Enforced by the graph, not by the model's good intentions."""

    max_steps: int = Field(ge=1)
    max_tokens: int = Field(ge=1)
    max_cost_usd: float = Field(gt=0)
    max_wall_seconds: float = Field(gt=0)


class BudgetUsage(StrictModel):
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    wall_seconds: float = 0.0
    tool_calls: int = 0


# --- Queue and events -------------------------------------------------------------


class JobKind(StrEnum):
    START_RUN = "start_run"
    RESUME_RUN = "resume_run"


class QueuedJob(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    run_id: str
    kind: JobKind = JobKind.START_RUN
    attempt: int = 1
    enqueued_at: datetime | None = None
    # Set by the queue adapter so acknowledge() can address the right message.
    receipt: str | None = None


class RunEventType(StrEnum):
    RUN_STATUS = "run_status"
    PLAN_UPDATED = "plan_updated"
    STEP_STATUS = "step_status"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    REASONING = "reasoning"
    OBSERVATION_RECORDED = "observation_recorded"
    INTERRUPT_RAISED = "interrupt_raised"
    INTERRUPT_RESOLVED = "interrupt_resolved"
    BUDGET_UPDATED = "budget_updated"
    REPORT_CHUNK = "report_chunk"
    REPORT_READY = "report_ready"
    RESUMED_FROM_CHECKPOINT = "resumed_from_checkpoint"
    WARNING = "warning"
    ERROR = "error"


class RunEvent(StrictModel):
    """One item on the live timeline.

    `sequence` is assigned per run by the publisher and is monotonic, so a client that
    reconnects can discard anything it has already rendered and the ordering test has
    something exact to assert on.
    """

    run_id: str
    sequence: int
    type: RunEventType
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
