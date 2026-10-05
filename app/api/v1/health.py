"""Liveness and readiness.

Two endpoints, because they answer different questions and a container orchestrator uses them
differently. `/health/live` asks "is this process running?" and must never touch a dependency,
or a database blip would cause a restart loop that cannot possibly help. `/health/ready` asks
"should traffic be routed here?" and does check dependencies.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.deps import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Process liveness")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", summary="Dependency readiness")
async def ready(container: ContainerDep, response: Response) -> dict[str, Any]:
    database_ok = await container.database.healthy()

    checks: dict[str, Any] = {
        "database": "ok" if database_ok else "unavailable",
        # Redis is optional by design, so its absence is reported without failing readiness.
        "queue": "redis" if container.has_redis else "in-process",
    }
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if database_ok else "degraded", "checks": checks}
