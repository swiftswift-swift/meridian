"""The single error taxonomy for the application.

Every failure that the API is willing to describe to a caller derives from `DomainError`.
Anything else reaching the API boundary is a bug and is reported as an opaque 500, because
leaking an unplanned exception message is how internal details and secrets escape.

The HTTP mapping lives on the exception itself rather than in the API layer so that a new
error type cannot be added without deciding its status code.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for every expected failure.

    Attributes mirror the RFC 9457 problem document fields so the API layer only has to
    rename them, not invent them.
    """

    status: int = 500
    title: str = "Internal Server Error"
    error_code: str = "internal_error"

    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra

    def as_problem(self, instance: str | None = None) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "type": f"https://meridian.local/problems/{self.error_code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.error_code,
        }
        if instance is not None:
            problem["instance"] = instance
        problem.update(self.extra)
        return problem


class ValidationError(DomainError):
    status = 422
    title = "Unprocessable Content"
    error_code = "validation_error"


class NotFoundError(DomainError):
    status = 404
    title = "Not Found"
    error_code = "not_found"


class ConflictError(DomainError):
    """Two writers raced, or a uniqueness constraint was violated."""

    status = 409
    title = "Conflict"
    error_code = "conflict"


class AuthenticationError(DomainError):
    status = 401
    title = "Unauthorized"
    error_code = "authentication_required"


class PermissionDeniedError(DomainError):
    status = 403
    title = "Forbidden"
    error_code = "permission_denied"


class RateLimitedError(DomainError):
    status = 429
    title = "Too Many Requests"
    error_code = "rate_limited"

    def __init__(self, detail: str, retry_after_seconds: int, **extra: Any) -> None:
        super().__init__(detail, retry_after_seconds=retry_after_seconds, **extra)
        self.retry_after_seconds = retry_after_seconds


class BudgetExceededError(DomainError):
    """A run hit one of its hard caps on steps, tokens, cost or wall time.

    This is not an HTTP-facing error in the normal path: the graph catches it and routes to
    synthesis so the user still gets a report. It surfaces over HTTP only when a caller asks
    to resume a run that has nothing left to spend.
    """

    status = 409
    title = "Budget Exceeded"
    error_code = "budget_exceeded"


class ToolError(DomainError):
    """A tool failed in a way the agent is expected to reason about and work around.

    Carries `retryable` so the tool wrapper can decide whether to back off and try again
    without parsing the message.
    """

    status = 502
    title = "Tool Failed"
    error_code = "tool_error"

    def __init__(
        self,
        detail: str,
        *,
        tool_name: str,
        retryable: bool = False,
        **extra: Any,
    ) -> None:
        super().__init__(detail, tool_name=tool_name, retryable=retryable, **extra)
        self.tool_name = tool_name
        self.retryable = retryable


class ExternalServiceError(DomainError):
    """A dependency outside this process misbehaved: the LLM, Redis, or an HTTP API."""

    status = 502
    title = "Bad Gateway"
    error_code = "external_service_error"

    def __init__(self, detail: str, *, service: str, retryable: bool = True, **extra: Any) -> None:
        super().__init__(detail, service=service, retryable=retryable, **extra)
        self.service = service
        self.retryable = retryable


class ConfigurationError(DomainError):
    """Settings are internally inconsistent. Raised at startup, never per request."""

    status = 500
    title = "Configuration Error"
    error_code = "configuration_error"


class SecurityViolationError(DomainError):
    """A guardrail refused an action: unsafe SQL, a blocked URL, or a tainted tool call.

    Separate from `ValidationError` because these are the events that must always be logged
    and surfaced in the UI, not quietly corrected.
    """

    status = 400
    title = "Request Refused"
    error_code = "security_violation"

    def __init__(self, detail: str, *, guardrail: str, **extra: Any) -> None:
        super().__init__(detail, guardrail=guardrail, **extra)
        self.guardrail = guardrail
