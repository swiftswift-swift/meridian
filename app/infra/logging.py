"""Structured logging with secret redaction.

Every log line is JSON in production so a log aggregator can filter on run_id and request_id
without regex. Redaction is applied as a processor rather than at each call site, because the
one call site that forgets is the one that leaks the key.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.typing import EventDict, WrappedLogger

from app.settings import LogFormat, Settings

# Keys whose values are never safe to print, matched case-insensitively on substrings so
# `openai_api_key`, `OPENAI_API_KEY` and `authorization` are all covered.
SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
)

REDACTED = "[redacted]"

# Depth cap for walking nested log payloads; deeper structures are logged as-is.
MAX_REDACTION_DEPTH = 4

# Catches a secret that arrives inside a message string rather than as its own field.
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.IGNORECASE)
_SK_PATTERN = re.compile(r"\b(sk-|gsk_|tvly-)[A-Za-z0-9_\-]{8,}")


def redact_processor(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    return _redact_mapping(event_dict)


def _redact_mapping(mapping: EventDict) -> EventDict:
    for key, value in list(mapping.items()):
        lowered = key.lower()
        if any(part in lowered for part in SENSITIVE_KEY_PARTS):
            mapping[key] = REDACTED
            continue
        mapping[key] = _redact_value(value)
    return mapping


def _redact_value(value: Any, depth: int = 0) -> Any:
    if depth > MAX_REDACTION_DEPTH:
        return value
    if isinstance(value, str):
        scrubbed = _BEARER_PATTERN.sub(r"\1" + REDACTED, value)
        return _SK_PATTERN.sub(REDACTED, scrubbed)
    if isinstance(value, dict):
        return {
            k: (
                REDACTED
                if any(part in str(k).lower() for part in SENSITIVE_KEY_PARTS)
                else _redact_value(v, depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, depth + 1) for item in value]
    return value


def configure_logging(settings: Settings) -> None:
    """Configure structlog and route the standard library through it.

    Everything is emitted through the stdlib logger rather than structlog's own PrintLogger, so
    uvicorn's and SQLAlchemy's records pass through the same processors and the output is
    uniformly JSON instead of half structured and half plain text.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Applied to records from this application and, via foreign_pre_chain, to records from
    # third-party libraries that never touched structlog.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_processor,
    ]

    renderer: Any
    if settings.log_format is LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            # Hands the event dict to the stdlib formatter below rather than rendering here.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    # stdout, not stderr: PowerShell 5.1 wraps a native command's stderr in ErrorRecords, which
    # makes ordinary structured log lines look like a failed command to tasks.ps1.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # SQLAlchemy at INFO echoes every statement, which drowns the run timeline.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def bind_request_context(**values: str) -> None:
    """Attach ids to every log line emitted while handling this request or run."""
    bind_contextvars(**values)


def clear_request_context() -> None:
    clear_contextvars()
