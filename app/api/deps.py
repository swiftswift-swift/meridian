"""FastAPI dependencies.

The container is reached through `request.app.state`, not a module global, so a test can build
an app with different adapters and the dependencies follow automatically.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.container import ServiceContainer
from app.domain.errors import AuthenticationError, PermissionDeniedError
from app.domain.models import Role
from app.domain.rbac import role_satisfies
from app.services.auth_service import AuthenticatedUser, AuthService

# auto_error=False so a missing header raises our AuthenticationError with a usable message
# rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, ServiceContainer):
        # Only reachable if an app is built without create_app, which is a wiring mistake
        # rather than a request problem, so it is deliberately not a DomainError.
        raise TypeError("The application was started without a ServiceContainer.")
    return container


ContainerDep = Annotated[ServiceContainer, Depends(get_container)]


def get_auth_service(container: ContainerDep) -> AuthService:
    return AuthService(container.database, container.settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    auth_service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Sign in to use this endpoint.")
    return await auth_service.resolve_token(credentials.credentials)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require_role(required: Role) -> Callable[[AuthenticatedUser], Awaitable[AuthenticatedUser]]:
    """Build a dependency that rejects callers below `required`.

    Used as `Depends(require_role(Role.ADMIN))` on admin routes so the check is declared on the
    route rather than repeated in its body.
    """

    async def _dependency(user: CurrentUser) -> AuthenticatedUser:
        if not role_satisfies(user.role, required):
            raise PermissionDeniedError(
                f"This action needs the {required.value} role; your account is {user.role.value}."
            )
        return user

    return _dependency


AdminUser = Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN))]
AnalystUser = Annotated[AuthenticatedUser, Depends(require_role(Role.ANALYST))]
