"""The application factory.

`create_app(settings)` is the only way an app is built. Uvicorn is pointed at the zero-argument
`app()` wrapper, which reads settings from the environment; tests call `create_app` directly
with whatever settings the case needs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.spa import mount_web_interface
from app.api.v1 import auth as auth_routes
from app.api.v1 import datasources as datasource_routes
from app.api.v1 import health as health_routes
from app.api.v1 import insights as insight_routes
from app.api.v1 import research as research_routes
from app.container import ServiceContainer
from app.infra.logging import configure_logging
from app.settings import Settings

logger = structlog.get_logger(__name__)

API_DESCRIPTION = """
Developer API for Meridian. The product interface is the web application at `/`; these docs are
for integrators and are intentionally unlinked from the site navigation.
""".strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        container = await ServiceContainer.create(resolved)
        application.state.container = container
        # Development convenience: create tables if migrations have not been run, so a fresh
        # clone serves a working site without a separate alembic step. Production images run
        # `alembic upgrade head` in the entrypoint, keeping migrations authoritative.
        if resolved.app_env.value in {"local", "test"}:
            await container.database.create_all()
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title="Meridian API",
        description=API_DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        # Swagger is available but deliberately not the product surface.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    _register_middleware(app, resolved)
    register_error_handlers(app)
    _register_routes(app)
    # Mounted last: its catch-all SPA route must not shadow an API path.
    mount_web_interface(app, resolved)
    return app


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    # Starlette runs middleware in reverse registration order, so the request-context
    # middleware is added last to make its id available to everything inside it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    app.add_middleware(RequestContextMiddleware)


def _register_routes(app: FastAPI) -> None:
    app.include_router(health_routes.router)
    for router in (
        auth_routes.router,
        datasource_routes.router,
        insight_routes.router,
        research_routes.router,
    ):
        app.include_router(router, prefix="/api/v1")


def app() -> FastAPI:
    """Entry point for `uvicorn app.main:app --factory`."""
    return create_app()
