"""Insights: aggregate run activity. Admin only, because it spans every user's runs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import String, cast, func, select

from app.api.deps import ContainerDep, require_role
from app.domain.models import Role
from app.infra.models import Report, Run

# Admin-only at the router level, so every endpoint added here inherits the restriction.
router = APIRouter(
    prefix="/insights",
    tags=["insights"],
    dependencies=[Depends(require_role(Role.ADMIN))],
)


@router.get("/summary")
async def summary(container: ContainerDep) -> dict[str, Any]:
    """Headline counters, the daily run trend, and outcome mix.

    Aggregation happens in SQL rather than by loading rows into Python, because this endpoint is
    polled by a dashboard and the row count grows without bound.
    """
    async with container.database.read_session() as session:
        total = await session.scalar(select(func.count()).select_from(Run)) or 0

        status_rows = (
            await session.execute(select(Run.status, func.count()).group_by(Run.status))
        ).all()
        by_status = {str(status): int(count) for status, count in status_rows}

        # SQLite stores these as ISO strings, so the date is the first ten characters. A real
        # PostgreSQL deployment would use date_trunc; this is the portable form.
        daily_rows = (
            await session.execute(
                select(
                    func.substr(cast(Run.created_at, String), 1, 10).label("day"),
                    func.count().label("runs"),
                )
                .group_by("day")
                .order_by("day")
            )
        ).all()

        verification = await session.scalar(select(func.avg(Report.verification_score)))
        # Run.usage["key"].as_float() compiles per dialect; func.json_extract is SQLite
        # only and would fail against the PostgreSQL that docker compose starts.
        avg_cost = await session.scalar(select(func.avg(Run.usage["cost_usd"].as_float())))
        avg_steps = await session.scalar(select(func.avg(Run.usage["steps"].as_float())))
        durations = (
            (
                await session.execute(
                    select(Run.usage["wall_seconds"].as_float()).where(Run.finished_at.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        budget_exhausted = (
            await session.scalar(
                select(func.count()).select_from(Run).where(Run.stopped_early_reason.is_not(None))
            )
            or 0
        )

    seconds = sorted(float(value) for value in durations if value is not None)
    return {
        "total_runs": total,
        "by_status": by_status,
        "completed": by_status.get("completed", 0),
        "failed": by_status.get("failed", 0),
        "success_rate": round(by_status.get("completed", 0) / total, 4) if total else 0.0,
        "budget_exhausted_rate": round(budget_exhausted / total, 4) if total else 0.0,
        "avg_verification_score": round(float(verification), 4) if verification else 0.0,
        "avg_cost_usd": round(float(avg_cost), 4) if avg_cost else 0.0,
        "avg_steps": round(float(avg_steps), 2) if avg_steps else 0.0,
        "p50_duration_seconds": _percentile(seconds, 0.50),
        "p95_duration_seconds": _percentile(seconds, 0.95),
        "daily": [{"day": str(day), "runs": int(runs)} for day, runs in daily_rows],
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile.

    No interpolation on purpose: with a few dozen runs, interpolating between two samples invents
    precision the data does not support.
    """
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))
    return round(sorted_values[index], 2)
