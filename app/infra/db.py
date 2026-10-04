"""Database engines and session management.

Two engines, on purpose:

* `app_engine` is read-write and owns everything the product writes: users, runs, reports.
* `company_engine` is the sample company data and is opened read-only. The SQL tool can only
  ever reach this one, so even a hypothetical guard bypass cannot modify product data.

The read-only guarantee is enforced twice: by parsing the statement before it runs
(`app.domain.sql_guard`) and by the connection itself (`PRAGMA query_only` on SQLite, a
read-only transaction on PostgreSQL). Defence in depth, because a parser is software too.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from app.infra.models import Base
from app.settings import Settings


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def create_app_engine(settings: Settings) -> AsyncEngine:
    """The read-write engine for product data."""
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        future=True,
        pool_pre_ping=True,
    )
    if _is_sqlite(settings.database_url):
        _apply_sqlite_pragmas(engine, read_only=False)
    return engine


def create_company_engine(settings: Settings) -> AsyncEngine:
    """The read-only engine the SQL tool uses."""
    engine = create_async_engine(
        settings.company_database_url,
        echo=settings.database_echo,
        future=True,
        pool_pre_ping=True,
    )
    if _is_sqlite(settings.company_database_url):
        _apply_sqlite_pragmas(engine, read_only=True)
    else:
        _apply_postgres_read_only(engine)
    return engine


def _apply_sqlite_pragmas(engine: AsyncEngine, *, read_only: bool) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
        cursor = dbapi_connection.cursor()
        try:
            # WAL lets the API read while the worker writes, which the live timeline depends on.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if read_only:
                cursor.execute("PRAGMA query_only=ON")
        finally:
            cursor.close()


def _apply_postgres_read_only(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(connection: Any) -> None:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")


@dataclass(slots=True)
class Database:
    """Owns the engines and hands out sessions.

    Held by the ServiceContainer rather than module-level globals so a test can build an
    isolated database per case and dispose it afterwards.
    """

    engine: AsyncEngine
    company_engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        engine = create_app_engine(settings)
        return cls(
            engine=engine,
            company_engine=create_company_engine(settings),
            session_factory=async_sessionmaker(
                engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
            ),
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session with commit-on-success, rollback-on-error."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        """A session that never commits, for query endpoints."""
        async with self.session_factory() as session:
            yield session

    async def create_all(self) -> None:
        """Create product tables directly, bypassing Alembic.

        Used by tests and by the seed script's first run. Production paths use
        `alembic upgrade head` so the migration history stays the source of truth.
        """
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def healthy(self) -> bool:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError):
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
        await self.company_engine.dispose()
