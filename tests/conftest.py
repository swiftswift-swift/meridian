"""Shared test fixtures.

Two rules hold for the whole suite:

1. No network and no API key. The offline providers are forced here rather than inherited from
   the developer's .env, so a machine with a real OPENAI_API_KEY exported still runs the same
   deterministic tests.
2. Every test gets its own database file. Tests then run in any order, and a failure leaves an
   inspectable artefact rather than poisoning the next case.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
from fastapi import FastAPI

# Set before any application import so Settings cannot pick up the developer's real providers.
os.environ.update(
    {
        "APP_ENV": "test",
        "LLM_PROVIDER": "scripted",
        "TOOLS_MODE": "fixtures",
        "EMBEDDING_PROVIDER": "hash",
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "console",
        "REDIS_URL": "",
        "OPENAI_API_KEY": "",
        "TAVILY_API_KEY": "",
    }
)

from app.container import ServiceContainer
from app.domain.models import Role
from app.infra.db import Database
from app.main import create_app
from app.services.auth_service import AuthenticatedUser, AuthService
from app.settings import Settings


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with TemporaryDirectory(prefix="meridian-test-") as raw:
        yield Path(raw)


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """Offline settings pointed at a throwaway directory."""
    return Settings(
        _env_file=None,
        app_env="test",
        data_dir=data_dir,
        database_url="sqlite+aiosqlite:///app.db",
        company_database_url="sqlite+aiosqlite:///company.db",
        checkpoint_database_url="sqlite:///checkpoints.db",
        jwt_secret="test-secret-not-used-anywhere-real",
        llm_provider="scripted",
        tools_mode="fixtures",
        embedding_provider="hash",
        log_level="WARNING",
        log_format="console",
        # Generous so a test asserting on behaviour is never tripped by the limiter.
        rate_limit_requests=10_000,
    )


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    settings.ensure_directories()
    db = Database.from_settings(settings)
    await db.create_all()
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[ServiceContainer]:
    settings.ensure_directories()
    instance = await ServiceContainer.create(settings)
    await instance.database.create_all()
    try:
        yield instance
    finally:
        await instance.aclose()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    """A real application with its lifespan run, so app.state.container exists."""
    instance = create_app(settings)
    async with instance.router.lifespan_context(instance):
        yield instance


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def auth_service(database: Database, settings: Settings) -> AuthService:
    return AuthService(database, settings)


@pytest.fixture
async def analyst(app: FastAPI) -> AuthenticatedUser:
    return await _make_user(app, "analyst@example.com", "Avery Analyst", Role.ANALYST)


@pytest.fixture
async def admin(app: FastAPI) -> AuthenticatedUser:
    return await _make_user(app, "admin@example.com", "Adele Admin", Role.ADMIN)


@pytest.fixture
async def viewer(app: FastAPI) -> AuthenticatedUser:
    return await _make_user(app, "viewer@example.com", "Vik Viewer", Role.VIEWER)


async def _make_user(app: FastAPI, email: str, name: str, role: Role) -> AuthenticatedUser:
    container: ServiceContainer = app.state.container
    service = AuthService(container.database, container.settings)
    user, _ = await service.sign_up(email, "test-password", name, role)
    return user


@pytest.fixture
def auth_header(app: FastAPI):
    """Build an Authorization header for a given user."""
    container: ServiceContainer = app.state.container
    service = AuthService(container.database, container.settings)

    def _header(user: AuthenticatedUser) -> dict[str, str]:
        return {"Authorization": f"Bearer {service.issue_token(user).access_token}"}

    return _header
