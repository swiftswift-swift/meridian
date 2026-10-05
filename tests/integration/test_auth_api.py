"""Authentication and RBAC over HTTP.

Marked integration because each case boots a real application with a real database; only the
model and external tools are substituted.
"""

from __future__ import annotations

import httpx
import pytest

from app.domain.models import Role
from app.services.auth_service import AuthenticatedUser

pytestmark = pytest.mark.integration

SIGNUP = "/api/v1/auth/signup"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
USERS = "/api/v1/auth/users"


async def test_signup_returns_a_usable_session(client: httpx.AsyncClient) -> None:
    response = await client.post(
        SIGNUP,
        json={"email": "new@example.com", "password": "a-good-password", "display_name": "New"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["role"] == "analyst"

    me = await client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


async def test_email_is_normalised(client: httpx.AsyncClient) -> None:
    await client.post(SIGNUP, json={"email": "  Mixed@Example.COM ", "password": "a-good-password"})
    # The same address in different case must be the same account.
    response = await client.post(
        LOGIN, json={"email": "mixed@example.com", "password": "a-good-password"}
    )
    assert response.status_code == 200


async def test_duplicate_email_is_a_conflict(client: httpx.AsyncClient) -> None:
    payload = {"email": "dupe@example.com", "password": "a-good-password"}
    assert (await client.post(SIGNUP, json=payload)).status_code == 201
    response = await client.post(SIGNUP, json=payload)
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "conflict"


async def test_short_password_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(SIGNUP, json={"email": "short@example.com", "password": "abc"})
    assert response.status_code == 422
    assert response.json()["errors"]


async def test_wrong_password_and_unknown_email_are_indistinguishable(
    client: httpx.AsyncClient,
) -> None:
    """A different message for each would let an attacker enumerate accounts."""
    await client.post(SIGNUP, json={"email": "real@example.com", "password": "a-good-password"})
    wrong_password = await client.post(
        LOGIN, json={"email": "real@example.com", "password": "not-the-password"}
    )
    unknown_email = await client.post(
        LOGIN, json={"email": "ghost@example.com", "password": "not-the-password"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


async def test_missing_token_is_unauthorised(client: httpx.AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


@pytest.mark.parametrize(
    "header",
    ["Bearer not.a.jwt", "Bearer ", "Basic abc123", "garbage"],
)
async def test_malformed_credentials_are_rejected(client: httpx.AsyncClient, header: str) -> None:
    response = await client.get(ME, headers={"Authorization": header})
    assert response.status_code == 401


async def test_token_signed_with_another_secret_is_rejected(client: httpx.AsyncClient) -> None:
    import jwt

    # At least 32 bytes, or PyJWT raises InsecureKeyLengthWarning instead of signing.
    forged = jwt.encode(
        {"sub": "someone", "exp": 9_999_999_999},
        "a-different-secret-of-sufficient-length",
    )
    response = await client.get(ME, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_analyst_cannot_list_users(
    client: httpx.AsyncClient, analyst: AuthenticatedUser, auth_header
) -> None:
    response = await client.get(USERS, headers=auth_header(analyst))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_admin_can_list_users(
    client: httpx.AsyncClient, admin: AuthenticatedUser, auth_header
) -> None:
    response = await client.get(USERS, headers=auth_header(admin))
    assert response.status_code == 200
    assert any(user["email"] == admin.email for user in response.json())


async def test_viewer_cannot_list_users(
    client: httpx.AsyncClient, viewer: AuthenticatedUser, auth_header
) -> None:
    assert (await client.get(USERS, headers=auth_header(viewer))).status_code == 403


async def test_admin_can_change_a_role(
    client: httpx.AsyncClient, admin: AuthenticatedUser, viewer: AuthenticatedUser, auth_header
) -> None:
    response = await client.put(
        f"{USERS}/{viewer.id}/role", json={"role": "analyst"}, headers=auth_header(admin)
    )
    assert response.status_code == 200
    assert response.json()["role"] == "analyst"


async def test_admin_cannot_demote_themselves(
    client: httpx.AsyncClient, admin: AuthenticatedUser, auth_header
) -> None:
    """Otherwise the last admin can lock every administrator out of the deployment."""
    response = await client.put(
        f"{USERS}/{admin.id}/role", json={"role": "viewer"}, headers=auth_header(admin)
    )
    assert response.status_code == 422


async def test_demo_login_without_seeded_accounts_explains_the_fix(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/auth/demo", json={"role": "analyst"})
    assert response.status_code == 404
    assert "seed" in response.json()["detail"].lower()


async def test_token_for_a_deleted_account_is_rejected(
    client: httpx.AsyncClient, analyst: AuthenticatedUser, auth_header, app
) -> None:
    """A valid signature is not enough; the account must still exist."""
    header = auth_header(analyst)
    assert (await client.get(ME, headers=header)).status_code == 200

    from sqlalchemy import delete

    from app.infra.models import User

    container = app.state.container
    async with container.database.session() as session:
        await session.execute(delete(User).where(User.id == analyst.id))

    assert (await client.get(ME, headers=header)).status_code == 401


async def test_role_escalation_via_a_forged_claim_is_ignored(
    client: httpx.AsyncClient, analyst: AuthenticatedUser, app
) -> None:
    """The role in the token is not trusted; the database row is authoritative."""
    import jwt

    settings = app.state.container.settings
    escalated = jwt.encode(
        {"sub": analyst.id, "role": "admin", "exp": 9_999_999_999},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    response = await client.get(USERS, headers={"Authorization": f"Bearer {escalated}"})
    assert response.status_code == 403


async def test_security_headers_are_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Request-ID"]


async def test_request_id_is_echoed_when_supplied(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "trace-me-123"})
    assert response.headers["X-Request-ID"] == "trace-me-123"


async def test_readiness_reports_its_dependencies(client: httpx.AsyncClient) -> None:
    body = (await client.get("/health/ready")).json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


async def test_role_hierarchy_is_respected(auth_service, database) -> None:
    """Admin satisfies analyst-level requirements, and viewer does not."""
    from app.domain.rbac import can_start_run, can_view_insights

    assert can_start_run(Role.ADMIN)
    assert can_start_run(Role.ANALYST)
    assert not can_start_run(Role.VIEWER)
    assert can_view_insights(Role.ADMIN)
    assert not can_view_insights(Role.ANALYST)
