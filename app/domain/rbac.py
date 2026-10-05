"""Role rules.

Pure functions so every endpoint's permission decision is testable without a request, a
database or a token. The role order is a simple hierarchy: anything an analyst may do, an admin
may do too.
"""

from __future__ import annotations

from app.domain.models import Role

# Higher rank implies every permission of the ranks below it.
_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.ANALYST: 1, Role.ADMIN: 2}


def role_satisfies(actual: Role, required: Role) -> bool:
    return _RANK[actual] >= _RANK[required]


def can_start_run(role: Role) -> bool:
    """Viewers can read research but not spend budget on new runs."""
    return role_satisfies(role, Role.ANALYST)


def can_manage_documents(role: Role) -> bool:
    return role_satisfies(role, Role.ANALYST)


def can_view_insights(role: Role) -> bool:
    """Insights aggregate every user's activity, so it is an admin view."""
    return role_satisfies(role, Role.ADMIN)


def can_manage_users(role: Role) -> bool:
    return role_satisfies(role, Role.ADMIN)


def can_view_run(role: Role, *, is_owner: bool) -> bool:
    """Admins audit any run; everyone else sees only their own."""
    return is_owner or role_satisfies(role, Role.ADMIN)
