"""Run history, saved reports and share links."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep, CurrentUser, get_current_user
from app.domain.errors import PermissionDeniedError
from app.domain.models import Role
from app.domain.rbac import can_start_run
from app.services.run_service import DEFAULT_PAGE_SIZE, RunService

router = APIRouter(prefix="/runs", tags=["runs"])


class RunSummaryView(BaseModel):
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


class RunPage(BaseModel):
    items: list[RunSummaryView]
    next_cursor: str | None
    total: int


class ShareView(BaseModel):
    share_token: str
    url: str


class AskAndSaveRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _service(container: ContainerDep) -> RunService:
    return RunService(container.database)


@router.get("", response_model=RunPage, dependencies=[Depends(get_current_user)])
async def list_runs(
    container: ContainerDep,
    user: CurrentUser,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> RunPage:
    """Newest first. An admin sees every user's runs; everyone else sees their own."""
    service = _service(container)
    items, next_cursor = await service.list_for(user.id, user.role, limit=limit, cursor=cursor)
    total = await service.count_for(user.id, user.role)
    return RunPage(
        items=[RunSummaryView(**asdict(item)) for item in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_current_user)])
async def create_run(
    payload: AskAndSaveRequest, container: ContainerDep, user: CurrentUser
) -> dict[str, Any]:
    """Investigate a question and keep the result.

    Viewers may read research but not commission it, since a run spends budget.
    """
    if not can_start_run(user.role):
        raise PermissionDeniedError("The viewer role can read research but not start new runs.")
    # Imported here so the module loads even when no model provider is configured.
    from app.api.v1.research import _build  # noqa: PLC0415

    research = _build(container)
    answer = await research.answer(payload.question)
    run_id = await _service(container).save(user.id, answer)
    return {"run_id": run_id, **asdict(answer)}


@router.get("/{run_id}", dependencies=[Depends(get_current_user)])
async def get_run(run_id: str, container: ContainerDep, user: CurrentUser) -> dict[str, Any]:
    return await _service(container).get(run_id, user.id, user.role)


@router.post("/{run_id}/share", response_model=ShareView, dependencies=[Depends(get_current_user)])
async def share_run(run_id: str, container: ContainerDep, user: CurrentUser) -> ShareView:
    token = await _service(container).create_share_link(run_id, user.id, user.role)
    base = container.settings.public_base_url.rstrip("/")
    return ShareView(share_token=token, url=f"{base}/shared/{token}")


@router.delete(
    "/{run_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_current_user)]
)
async def delete_run(run_id: str, container: ContainerDep, user: CurrentUser) -> Response:
    await _service(container).delete(run_id, user.id, user.role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Deliberately outside the authenticated router: a share link is readable by anyone holding it,
# which is the point of sharing a report with someone who has no account.
public_router = APIRouter(prefix="/shared", tags=["runs"])


@public_router.get("/{share_token}")
async def get_shared(share_token: str, container: ContainerDep) -> dict[str, Any]:
    return await RunService(container.database).get_shared(share_token)


def viewer_can_read(role: Role) -> bool:
    """Exposed for tests: every role may read a run they own."""
    return role in {Role.VIEWER, Role.ANALYST, Role.ADMIN}
