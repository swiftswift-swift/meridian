"""Persist research runs so history, sharing and auditing are possible.

A run is written once it finishes rather than streamed as it goes, because this build has no
worker: the request that asks the question is the one that does the work. The row shape is the
durable one the worker will write into later, so adopting it now avoids a migration.

Observations are stored per query with their source id, which is what makes a citation chip on
a saved report resolve months later without re-running anything.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.domain.errors import NotFoundError, PermissionDeniedError
from app.domain.models import Role
from app.infra.db import Database
from app.infra.models import Observation, Report, Run, RunStep
from app.services.research_service import ResearchAnswer

# A page of history. Small enough to stay fast, large enough that most users never paginate.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: str
    question: str
    status: str
    title: str
    verification_score: float
    cost_usd: float
    duration_ms: int
    query_count: int
    model: str
    created_at: datetime
    share_token: str | None


class RunService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def save(self, user_id: str, answer: ResearchAnswer) -> str:
        """Write a finished run, its steps, its observations and its report."""
        now = datetime.now(UTC)
        async with self._database.session() as session:
            run = Run(
                user_id=user_id,
                question=answer.question,
                status="completed" if answer.answerable else "failed",
                plan={"steps": answer.plan, "revision": 0},
                budget={
                    "max_steps": len(answer.plan) or 1,
                    "max_tokens": 120_000,
                    "max_cost_usd": 0.5,
                    "max_wall_seconds": 300.0,
                },
                usage={
                    "steps": len(answer.steps),
                    "tokens": answer.tokens,
                    "cost_usd": answer.cost_usd,
                    "wall_seconds": answer.elapsed_ms / 1000,
                    "tool_calls": len(answer.steps),
                    "model": answer.model,
                },
                allowed_tools=["sql_query"],
                error=None if answer.answerable else answer.message,
                started_at=now,
                finished_at=now,
            )
            session.add(run)
            await session.flush()

            for index, plan_step in enumerate(answer.plan):
                session.add(
                    RunStep(
                        run_id=run.id,
                        step_index=index,
                        description=plan_step,
                        intended_tools=["sql_query"],
                        status="done" if answer.answerable else "skipped",
                        started_at=now,
                        finished_at=now,
                    )
                )

            for index, step in enumerate(answer.steps):
                session.add(
                    Observation(
                        run_id=run.id,
                        source_id=step.source_id,
                        step_index=index,
                        tool_name="sql_query",
                        summary=step.purpose,
                        payload={
                            "sql": step.executed_sql or step.sql,
                            "columns": step.columns,
                            # Capped: a saved run should not grow without bound, and the panel
                            # only ever renders the first screenful.
                            "rows": step.rows[:50],
                            "row_count": step.row_count,
                        },
                        display={
                            "ok": step.ok,
                            "refused": step.refused,
                            "reason": step.reason,
                            "latency_ms": step.latency_ms,
                        },
                    )
                )

            if answer.answerable:
                session.add(
                    Report(
                        run_id=run.id,
                        title=answer.title,
                        executive_summary=answer.body[:600],
                        markdown=answer.body,
                        limitations=[answer.limitation] if answer.limitation else [],
                        verification_score=answer.verification_score,
                        verification_detail={
                            "removed_claims": answer.removed_claims,
                            "model": answer.model,
                        },
                        unsupported_claims=answer.removed_claims,
                    )
                )
            await session.flush()
            return run.id

    async def list_for(
        self, user_id: str, role: Role, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None
    ) -> tuple[list[RunSummary], str | None]:
        """Newest first, with an opaque cursor.

        Keyset pagination on (created_at, id) rather than OFFSET: offset re-scans everything it
        skips and shifts when a new run is inserted mid-scroll.
        """
        size = max(1, min(limit, MAX_PAGE_SIZE))
        query = select(Run, Report).outerjoin(Report, Report.run_id == Run.id)
        if role is not Role.ADMIN:
            query = query.where(Run.user_id == user_id)
        if cursor:
            created, _, run_id = cursor.partition("|")
            query = query.where(
                (Run.created_at < datetime.fromisoformat(created))
                | ((Run.created_at == datetime.fromisoformat(created)) & (Run.id < run_id))
            )
        query = query.order_by(Run.created_at.desc(), Run.id.desc()).limit(size + 1)

        async with self._database.read_session() as session:
            rows = (await session.execute(query)).all()

        has_more = len(rows) > size
        page = rows[:size]
        summaries = [self._summarise(run, report) for run, report in page]
        next_cursor = None
        if has_more and page:
            last_run = page[-1][0]
            next_cursor = f"{last_run.created_at.isoformat()}|{last_run.id}"
        return summaries, next_cursor

    async def get(self, run_id: str, user_id: str, role: Role) -> dict[str, Any]:
        async with self._database.read_session() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("That run does not exist.")
            if run.user_id != user_id and role is not Role.ADMIN:
                raise PermissionDeniedError("That run belongs to someone else.")
            report = await session.scalar(select(Report).where(Report.run_id == run_id))
            observations = (
                await session.scalars(
                    select(Observation)
                    .where(Observation.run_id == run_id)
                    .order_by(Observation.source_id)
                )
            ).all()
        return self._detail(run, report, list(observations))

    async def get_shared(self, share_token: str) -> dict[str, Any]:
        """Resolve a read-only share link. No authentication: the token is the credential."""
        async with self._database.read_session() as session:
            run = await session.scalar(select(Run).where(Run.share_token == share_token))
            if run is None:
                raise NotFoundError("That share link is not valid.")
            report = await session.scalar(select(Report).where(Report.run_id == run.id))
            observations = (
                await session.scalars(
                    select(Observation)
                    .where(Observation.run_id == run.id)
                    .order_by(Observation.source_id)
                )
            ).all()
        return self._detail(run, report, list(observations))

    async def create_share_link(self, run_id: str, user_id: str, role: Role) -> str:
        async with self._database.session() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("That run does not exist.")
            if run.user_id != user_id and role is not Role.ADMIN:
                raise PermissionDeniedError("That run belongs to someone else.")
            if not run.share_token:
                # 32 urlsafe characters; guessing one is not a realistic attack.
                run.share_token = secrets.token_urlsafe(24)
            await session.flush()
            return str(run.share_token)

    async def delete(self, run_id: str, user_id: str, role: Role) -> None:
        async with self._database.session() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise NotFoundError("That run does not exist.")
            if run.user_id != user_id and role is not Role.ADMIN:
                raise PermissionDeniedError("That run belongs to someone else.")
            await session.delete(run)

    async def count_for(self, user_id: str, role: Role) -> int:
        query = select(func.count()).select_from(Run)
        if role is not Role.ADMIN:
            query = query.where(Run.user_id == user_id)
        async with self._database.read_session() as session:
            return await session.scalar(query) or 0

    @staticmethod
    def _summarise(run: Run, report: Report | None) -> RunSummary:
        usage = run.usage or {}
        return RunSummary(
            id=run.id,
            question=run.question,
            status=run.status,
            title=report.title if report else (run.error or "No answer"),
            verification_score=report.verification_score if report else 0.0,
            cost_usd=float(usage.get("cost_usd", 0.0)),
            duration_ms=int(float(usage.get("wall_seconds", 0.0)) * 1000),
            query_count=int(usage.get("tool_calls", 0)),
            model=str(usage.get("model", "")),
            created_at=run.created_at,
            share_token=run.share_token,
        )

    @staticmethod
    def _detail(run: Run, report: Report | None, observations: list[Observation]) -> dict[str, Any]:
        usage = run.usage or {}
        return {
            "id": run.id,
            "question": run.question,
            "status": run.status,
            "error": run.error,
            "plan": (run.plan or {}).get("steps", []),
            "usage": usage,
            "created_at": run.created_at.isoformat(),
            "share_token": run.share_token,
            "report": None
            if report is None
            else {
                "title": report.title,
                "body": report.markdown,
                "limitations": report.limitations,
                "verification_score": report.verification_score,
                "removed_claims": report.unsupported_claims,
            },
            "observations": [
                {
                    "source_id": observation.source_id,
                    "purpose": observation.summary,
                    "sql": (observation.payload or {}).get("sql", ""),
                    "columns": (observation.payload or {}).get("columns", []),
                    "rows": (observation.payload or {}).get("rows", []),
                    "row_count": (observation.payload or {}).get("row_count", 0),
                    "ok": (observation.display or {}).get("ok", True),
                    "refused": (observation.display or {}).get("refused", False),
                    "reason": (observation.display or {}).get("reason", ""),
                    "latency_ms": (observation.display or {}).get("latency_ms", 0),
                }
                for observation in observations
            ],
        }
