"""RFC 9457 problem+json error responses.

One shape for every failure, so the frontend has exactly one error branch to write. The
handlers are registered on the app in `create_app`; nothing raises HTTPException directly in
this codebase, because that would bypass the taxonomy.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import DomainError, RateLimitedError, SecurityViolationError

PROBLEM_CONTENT_TYPE = "application/problem+json"
SERVER_ERROR_THRESHOLD = 500
logger = structlog.get_logger(__name__)


def _problem_response(
    status: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    # Starlette types every handler as taking Exception, so each one re-narrows. Falling through
    # to the generic handler is the safe response to an unexpected type, not a crash.
    if not isinstance(exc, DomainError):
        return await handle_unexpected_error(request, exc)
    problem = exc.as_problem(instance=request.url.path)
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after_seconds)

    if isinstance(exc, SecurityViolationError):
        # Guardrail refusals are the events an operator most wants in the log, and they are
        # expected behaviour rather than faults, so they are logged at warning, not error.
        logger.warning(
            "guardrail.refused",
            guardrail=exc.guardrail,
            detail=exc.detail,
            path=request.url.path,
        )
    elif exc.status >= SERVER_ERROR_THRESHOLD:
        logger.error("domain.error", code=exc.error_code, detail=exc.detail, path=request.url.path)
    return _problem_response(exc.status, problem, headers or None)


async def handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return await handle_unexpected_error(request, exc)
    # Pydantic's error objects contain non-serialisable context; only the parts a client can act
    # on are forwarded.
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            "message": error.get("msg", "Invalid value."),
        }
        for error in exc.errors()
    ]
    return _problem_response(
        422,
        {
            "type": "https://meridian.local/problems/validation_error",
            "title": "Unprocessable Content",
            "status": 422,
            "detail": "The request body did not match what this endpoint expects.",
            "code": "validation_error",
            "instance": request.url.path,
            "errors": fields,
        },
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return await handle_unexpected_error(request, exc)
    return _problem_response(
        exc.status_code,
        {
            "type": f"https://meridian.local/problems/http_{exc.status_code}",
            "title": str(exc.detail),
            "status": exc.status_code,
            "detail": str(exc.detail),
            "code": f"http_{exc.status_code}",
            "instance": request.url.path,
        },
        headers=getattr(exc, "headers", None),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort.

    An unplanned exception is a bug, so the client gets a correlation id and nothing else. The
    message could contain a connection string or a row of customer data, and the log is the
    right place for it.
    """
    incident_id = uuid.uuid4().hex[:12]
    logger.exception(
        "unhandled.exception",
        incident_id=incident_id,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return _problem_response(
        500,
        {
            "type": "https://meridian.local/problems/internal_error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": (
                "Something failed on our side. Quote this incident id if you report it: "
                f"{incident_id}."
            ),
            "code": "internal_error",
            "instance": request.url.path,
            "incident_id": incident_id,
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
