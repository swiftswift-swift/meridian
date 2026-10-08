"""Saved runs over HTTP: history, permissions, sharing and deletion.

The run creation endpoint needs a model provider, so these cases write runs through the service
directly and exercise the read, share and delete paths over HTTP. That split is deliberate: it
keeps the suite offline while still covering every route a user can reach.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.domain.models import Role
from app.services.auth_service import AuthenticatedUser
from app.services.research_service import ResearchAnswer, ResearchStep
from app.services.run_service import RunService
from tests.conftest import AuthHeaderFactory

pytestmark = pytest.mark.integration


def sample_answer(question: str = "Which region leads?", score: float = 1.0) -> ResearchAnswer:
    return ResearchAnswer(
        question=question,
        answerable=True,
        plan=["Add up revenue by region"],
        steps=[
            ResearchStep(
                source_id="S1",
                purpose="Revenue by region",
                sql="SELECT r.code, SUM(o.subtotal_usd) FROM orders o",
                executed_sql="SELECT r.code, SUM(o.subtotal_usd) FROM orders o LIMIT 500",
                ok=True,
                columns=["code", "revenue_usd"],
                rows=[{"code": "EMEA", "revenue_usd": 4000.0}],
                row_count=1,
                latency_ms=12,
            )
        ],
        title="EMEA leads",
        body="EMEA generated $4,000 [S1].",
        limitation="Based on one query.",
        verification_score=score,
        model="scripted-test",
        tokens=280,
        cost_usd=0.0031,
        elapsed_ms=1200,
    )


async def save_one(app: FastAPI, user: AuthenticatedUser, **kwargs: object) -> str:
    service = RunService(app.state.container.database)
    return await service.save(user.id, sample_answer(**kwargs))  # type: ignore[arg-type]


async def test_a_saved_run_is_readable_by_its_owner(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    run_id = await save_one(app, analyst)
    response = await client.get(f"/api/v1/runs/{run_id}", headers=auth_header(analyst))

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "Which region leads?"
    assert body["report"]["title"] == "EMEA leads"
    assert body["report"]["verification_score"] == 1.0
    assert body["plan"] == ["Add up revenue by region"]


async def test_the_evidence_survives_the_round_trip(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    """A citation chip on a month-old report has to resolve without re-running anything."""
    run_id = await save_one(app, analyst)
    body = (await client.get(f"/api/v1/runs/{run_id}", headers=auth_header(analyst))).json()

    observation = body["observations"][0]
    assert observation["source_id"] == "S1"
    assert observation["rows"] == [{"code": "EMEA", "revenue_usd": 4000.0}]
    assert "LIMIT 500" in observation["sql"]
    assert observation["ok"] is True


async def test_another_users_run_is_not_readable(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    viewer: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    run_id = await save_one(app, analyst)
    response = await client.get(f"/api/v1/runs/{run_id}", headers=auth_header(viewer))
    assert response.status_code == 403


async def test_an_admin_may_read_any_run(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    admin: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    """Admins audit the deployment, so the listing and the detail both span every user."""
    run_id = await save_one(app, analyst)
    assert (
        await client.get(f"/api/v1/runs/{run_id}", headers=auth_header(admin))
    ).status_code == 200

    listing = (await client.get("/api/v1/runs", headers=auth_header(admin))).json()
    assert any(item["id"] == run_id for item in listing["items"])


async def test_history_lists_newest_first_and_only_your_own(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    viewer: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    await save_one(app, analyst, question="First question")
    await save_one(app, analyst, question="Second question")
    await save_one(app, viewer, question="Someone else's question")

    body = (await client.get("/api/v1/runs", headers=auth_header(analyst))).json()
    questions = [item["question"] for item in body["items"]]

    assert body["total"] == 2
    assert questions == ["Second question", "First question"]
    assert "Someone else's question" not in questions


async def test_pagination_returns_a_cursor_and_no_duplicates(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    for index in range(5):
        await save_one(app, analyst, question=f"Question {index}")

    first = (await client.get("/api/v1/runs?limit=2", headers=auth_header(analyst))).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]

    cursor = first["next_cursor"]
    second = (
        await client.get(f"/api/v1/runs?limit=2&cursor={cursor}", headers=auth_header(analyst))
    ).json()

    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert not (first_ids & second_ids)


async def test_a_share_link_is_readable_without_signing_in(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    """The token is the credential: that is the point of sending a report to someone."""
    run_id = await save_one(app, analyst)
    share = await client.post(f"/api/v1/runs/{run_id}/share", headers=auth_header(analyst))
    assert share.status_code == 200
    token = share.json()["share_token"]
    assert len(token) >= 20

    anonymous = await client.get(f"/api/v1/shared/{token}")
    assert anonymous.status_code == 200
    assert anonymous.json()["report"]["title"] == "EMEA leads"


async def test_sharing_twice_keeps_the_same_link(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    run_id = await save_one(app, analyst)
    first = (await client.post(f"/api/v1/runs/{run_id}/share", headers=auth_header(analyst))).json()
    second = (
        await client.post(f"/api/v1/runs/{run_id}/share", headers=auth_header(analyst))
    ).json()
    assert first["share_token"] == second["share_token"]


async def test_an_invented_share_token_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/shared/definitely-not-a-real-token")
    assert response.status_code == 404


async def test_a_run_can_be_deleted_by_its_owner(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    run_id = await save_one(app, analyst)
    assert (
        await client.delete(f"/api/v1/runs/{run_id}", headers=auth_header(analyst))
    ).status_code == 204
    assert (
        await client.get(f"/api/v1/runs/{run_id}", headers=auth_header(analyst))
    ).status_code == 404


async def test_deleting_someone_elses_run_is_refused(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    viewer: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    run_id = await save_one(app, analyst)
    assert (
        await client.delete(f"/api/v1/runs/{run_id}", headers=auth_header(viewer))
    ).status_code == 403


async def test_history_needs_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/runs")).status_code == 401


async def test_a_viewer_may_not_start_a_run(
    client: httpx.AsyncClient, viewer: AuthenticatedUser, auth_header: AuthHeaderFactory
) -> None:
    """Reading research is free; commissioning it spends budget."""
    response = await client.post(
        "/api/v1/runs", json={"question": "Anything at all"}, headers=auth_header(viewer)
    )
    assert response.status_code == 403
    assert "viewer" in response.json()["detail"].lower()


async def test_a_failed_run_is_stored_without_a_report(
    client: httpx.AsyncClient,
    app: FastAPI,
    analyst: AuthenticatedUser,
    auth_header: AuthHeaderFactory,
) -> None:
    answer = sample_answer()
    answer.answerable = False
    answer.message = "The schema holds no employee records."
    run_id = await RunService(app.state.container.database).save(analyst.id, answer)

    body = (await client.get(f"/api/v1/runs/{run_id}", headers=auth_header(analyst))).json()
    assert body["status"] == "failed"
    assert body["report"] is None
    assert "employee" in body["error"]


async def test_roles_are_respected_in_the_domain_rules() -> None:
    from app.domain.rbac import can_start_run, can_view_run

    assert can_start_run(Role.ANALYST)
    assert not can_start_run(Role.VIEWER)
    assert can_view_run(Role.VIEWER, is_owner=True)
    assert not can_view_run(Role.VIEWER, is_owner=False)
    assert can_view_run(Role.ADMIN, is_owner=False)
