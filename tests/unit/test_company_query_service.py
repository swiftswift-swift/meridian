"""The execution half of the SQL tool.

The guard is tested on its own in test_sql_guard.py; these cases prove the service honours its
verdict, shapes results the way the UI expects, and never lets a refusal look like an empty
result.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.db import Database
from app.services.company_query_service import CompanyQueryService
from app.settings import Settings
from company_db.schema import DDL

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def company(settings: Settings) -> AsyncIterator[Database]:
    """A tiny company database: enough rows to prove shaping, few enough to assert on."""
    settings.ensure_directories()
    database = Database.from_settings(settings)

    writable = create_async_engine(str(database.company_engine.url), future=True)
    try:
        async with writable.begin() as connection:
            for statement in DDL:
                await connection.execute(text(statement))
            await connection.execute(
                text("INSERT INTO regions (id, name, code) VALUES (1, 'EMEA', 'EMEA')")
            )
            await connection.execute(
                text("INSERT INTO regions (id, name, code) VALUES (2, 'Americas', 'AMER')")
            )
            await connection.execute(
                text("INSERT INTO currencies (code, name, symbol) VALUES ('USD', 'Dollar', '$')")
            )
            await connection.execute(
                text(
                    "INSERT INTO countries (id, region_id, name, iso_code, currency_code) "
                    "VALUES (1, 1, 'Germany', 'DE', 'USD')"
                )
            )
    finally:
        await writable.dispose()
    yield database
    # Windows will not delete the temp directory while a SQLite handle is open.
    await database.dispose()


@pytest.fixture
def service(company: Database) -> CompanyQueryService:
    return CompanyQueryService(company, row_limit=5, timeout_seconds=5.0)


async def test_allowed_query_returns_typed_rows(service: CompanyQueryService) -> None:
    result = await service.run("SELECT code, name FROM regions ORDER BY code")
    assert result.ok
    assert result.columns == ["code", "name"]
    assert result.rows[0] == {"code": "AMER", "name": "Americas"}
    assert result.row_count == 2
    assert result.referenced_tables == ["regions"]


async def test_refusal_is_not_an_empty_result(service: CompanyQueryService) -> None:
    """A refused query and a query returning nothing must be distinguishable.

    If they were not, the UI would render "no rows found" for a blocked statement and the user
    would never learn a guardrail fired.
    """
    refused = await service.run("DROP TABLE regions")
    assert refused.refused
    assert not refused.ok
    assert refused.guardrail == "read_only_sql"
    assert "SELECT" in refused.reason

    empty = await service.run("SELECT code FROM regions WHERE code = 'NOPE'")
    assert empty.ok
    assert not empty.refused
    assert empty.row_count == 0


async def test_row_limit_is_applied_to_the_executed_sql(service: CompanyQueryService) -> None:
    result = await service.run("SELECT * FROM regions")
    assert result.limit_applied == 5
    assert "LIMIT 5" in result.executed_sql.upper()


async def test_a_database_error_is_reported_without_the_driver_noise(
    service: CompanyQueryService,
) -> None:
    # The column passes the guard's allowlist but the table does not have it populated in a way
    # SQLite accepts here; what matters is the shape of the failure, not its cause.
    result = await service.run("SELECT code FROM regions GROUP BY nonexistent_alias")
    assert not result.ok
    assert result.reason
    assert "Traceback" not in result.reason


async def test_sample_rows_go_through_the_guard(service: CompanyQueryService) -> None:
    """An invented table name must be refused by the guard, not reach the database."""
    good = await service.sample_rows("regions")
    assert good.ok

    bad = await service.sample_rows("secrets")
    assert bad.refused
    assert "secrets" in bad.reason


async def test_schema_description_lists_every_table(service: CompanyQueryService) -> None:
    description = service.schema_for_planner()
    for table in ("orders", "customers", "marketing_spend"):
        assert table in description


async def test_describe_schema_reports_row_counts(service: CompanyQueryService) -> None:
    tables = await service.describe_schema()
    regions = next(table for table in tables if table["name"] == "regions")
    assert regions["row_count"] == 2
    assert "code" in regions["columns"]
    assert regions["description"]


async def test_the_company_engine_cannot_write(service: CompanyQueryService) -> None:
    """Defence in depth: even bypassing the guard, the connection refuses to modify anything."""
    from sqlalchemy.exc import SQLAlchemyError

    with pytest.raises(SQLAlchemyError):
        async with service._database.company_engine.begin() as connection:
            await connection.execute(text("DELETE FROM regions"))
