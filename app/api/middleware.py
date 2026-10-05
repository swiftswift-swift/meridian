"""Request middleware: correlation ids, security headers, access logs, rate limiting."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.errors import handle_domain_error
from app.domain.errors import RateLimitedError
from app.domain.ports import RateLimiterPort
from app.infra.logging import bind_request_context, clear_request_context

logger = structlog.get_logger(__name__)

RequestHandler = Callable[[Request], Awaitable[Response]]

# A caller-supplied correlation id longer than this is discarded rather than logged.
MAX_INBOUND_REQUEST_ID_LENGTH = 64

# Paths excluded from the access log: the probes would otherwise dominate it, and the SSE
# stream stays open for minutes so a completion log line is misleading.
_QUIET_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# The frontend is bundled, so no inline script is needed; 'unsafe-inline' for styles is the one
# concession, because Tailwind's runtime injects a style element for dynamic values.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, binds it to the logger, and logs the outcome."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        incoming = request.headers.get("X-Request-ID")
        request_id = (
            incoming
            if incoming and len(incoming) <= MAX_INBOUND_REQUEST_ID_LENGTH
            else uuid.uuid4().hex[:16]
        )
        request.state.request_id = request_id

        clear_request_context()
        bind_request_context(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handler produces the response; this only records the timing that
            # the handler cannot see.
            logger.exception(
                "request.failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            clear_request_context()

        response.headers["X-Request-ID"] = request_id
        if request.url.path not in _QUIET_PATHS:
            logger.info(
                "request.completed",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # The interactive API docs load Swagger's bundle from a CDN, so the strict policy is
        # applied everywhere except that one unlinked developer page.
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-caller rate limit on the API surface.

    Keyed by authenticated user when a token is present and by client address otherwise, so one
    noisy tenant cannot exhaust the limit for everyone behind the same proxy.
    """

    def __init__(self, app: ASGIApp, *, limit: int, window_seconds: int) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if not request.url.path.startswith("/api/v1") or request.url.path in _QUIET_PATHS:
            return await call_next(request)

        # The limiter lives on the container, which is built during lifespan startup and so does
        # not exist when middleware is registered. Resolving it per request also means a
        # deployment that gains Redis picks up the shared limiter without a code change.
        limiter = self._limiter_from(request)
        if limiter is None:
            return await call_next(request)

        key = self._caller_key(request)
        allowed, retry_after = await limiter.check(
            key, limit=self._limit, window_seconds=self._window_seconds
        )
        if not allowed:
            error = RateLimitedError(
                "Too many requests. Slow down and try again shortly.",
                retry_after_seconds=retry_after,
            )
            return await handle_domain_error(request, error)
        return await call_next(request)

    @staticmethod
    def _limiter_from(request: Request) -> RateLimiterPort | None:
        container = getattr(request.app.state, "container", None)
        if container is None:
            return None
        limiter: RateLimiterPort = container.rate_limiter
        return limiter

    @staticmethod
    def _caller_key(request: Request) -> str:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            # The token tail is enough to separate callers and is not itself a usable secret.
            return f"token:{authorization[-24:]}"
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"
