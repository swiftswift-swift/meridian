"""Read-only access to the sample company database.

This is the execution half of the `sql_query` tool: the guard decides whether a statement may
run, this runs it against the read-only engine and shapes the result for display.

Separated from the tool wrapper so the UI can expose a guard playground without pulling in the
agent's retry, circuit-breaker and ledger machinery.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.domain.sql_guard import SqlSchema, validate_sql
from app.infra.db import Database
from company_db.schema import TABLE_COLUMNS, TABLE_DESCRIPTIONS, schema_description

COMPANY_SCHEMA = SqlSchema.from_mapping(TABLE_COLUMNS)


@dataclass(slots=True)
class QueryResult:
    """One attempted query: refused by the guard, failed in the database, or successful."""

    ok: bool
    sql: str
    executed_sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    latency_ms: int = 0
    refused: bool = False
    reason: str = ""
    guardrail: str = ""
    referenced_tables: list[str] = field(default_factory=list)
    limit_applied: int | None = None


class CompanyQueryService:
    def __init__(self, database: Database, *, row_limit: int, timeout_seconds: float) -> None:
        self._database = database
        self._row_limit = row_limit
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def schema_for_planner() -> str:
        return schema_description()

    async def describe_schema(self) -> list[dict[str, Any]]:
        """Table, column and row-count listing for the schema browser."""
        tables: list[dict[str, Any]] = []
        async with self._database.company_engine.connect() as connection:
            for table, columns in TABLE_COLUMNS.items():
                # The table name comes from a module-level constant, never from a request.
                count = await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                tables.append(
                    {
                        "name": table,
                        "columns": columns,
                        "description": TABLE_DESCRIPTIONS.get(table, ""),
                        "row_count": int(count.scalar() or 0),
                    }
                )
        return tables

    async def sample_rows(self, table: str, limit: int = 5) -> QueryResult:
        """A few rows from one table, routed through the guard like any other query."""
        return await self.run(f"SELECT * FROM {table} LIMIT {limit}")  # noqa: S608

    async def run(self, sql: str) -> QueryResult:
        """Validate, then execute if allowed.

        Returns a result object in every case. A refusal is an expected outcome that the agent
        and the UI both need to read, not an exception.
        """
        decision = validate_sql(sql, COMPANY_SCHEMA, max_rows=self._row_limit)
        if not decision.allowed:
            return QueryResult(
                ok=False,
                sql=sql,
                refused=True,
                reason=decision.reason,
                guardrail="read_only_sql",
                referenced_tables=sorted(decision.referenced_tables),
            )

        started = time.perf_counter()
        try:
            rows, columns = await asyncio.wait_for(
                self._execute(decision.safe_sql), timeout=self._timeout_seconds
            )
        except TimeoutError:
            return QueryResult(
                ok=False,
                sql=sql,
                executed_sql=decision.safe_sql,
                reason=f"The query exceeded the {self._timeout_seconds:.0f} second limit.",
                guardrail="statement_timeout",
            )
        except SQLAlchemyError as exc:
            # The database's own complaint is useful to an analyst, but the driver prefix and any
            # connection detail are not.
            message = str(getattr(exc, "orig", exc)).split("\n")[0]
            return QueryResult(ok=False, sql=sql, executed_sql=decision.safe_sql, reason=message)

        return QueryResult(
            ok=True,
            sql=sql,
            executed_sql=decision.safe_sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            latency_ms=int((time.perf_counter() - started) * 1000),
            referenced_tables=sorted(decision.referenced_tables),
            limit_applied=decision.limit_applied,
        )

    async def _execute(self, sql: str) -> tuple[list[dict[str, Any]], list[str]]:
        async with self._database.company_engine.connect() as connection:
            result = await connection.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        return rows, columns
