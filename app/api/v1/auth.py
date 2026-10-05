"""Authentication endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import AdminUser, AuthServiceDep, CurrentUser
from app.domain.models import Role
from app.services.auth_service import AuthenticatedUser, IssuedToken

router = APIRouter(prefix="/auth", tags=["auth"])


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class DemoSignInRequest(BaseModel):
    role: Role = Role.ANALYST


class UserView(BaseModel):
    id: str
    email: str
    display_name: str
    role: Role
    is_demo: bool

    @classmethod
    def of(cls, user: AuthenticatedUser) -> UserView:
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            is_demo=user.is_demo,
        )


class SessionView(BaseModel):
    access_token: str
    token_type: str
    expires_at: datetime
    user: UserView

    @classmethod
    def of(cls, user: AuthenticatedUser, token: IssuedToken) -> SessionView:
        return cls(
            access_token=token.access_token,
            token_type=token.token_type,
            expires_at=token.expires_at,
            user=UserView.of(user),
        )


class SetRoleRequest(BaseModel):
    role: Role


@router.post("/signup", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def sign_up(payload: SignUpRequest, auth_service: AuthServiceDep) -> SessionView:
    user, token = await auth_service.sign_up(
        email=str(payload.email),
        password=payload.password,
        display_name=payload.display_name,
    )
    return SessionView.of(user, token)


@router.post("/login", response_model=SessionView)
async def sign_in(payload: SignInRequest, auth_service: AuthServiceDep) -> SessionView:
    user, token = await auth_service.sign_in(str(payload.email), payload.password)
    return SessionView.of(user, token)


@router.post("/demo", response_model=SessionView, summary="One-click sign-in as a demo account")
async def sign_in_demo(payload: DemoSignInRequest, auth_service: AuthServiceDep) -> SessionView:
    user, token = await auth_service.sign_in_demo(payload.role)
    return SessionView.of(user, token)


@router.get("/me", response_model=UserView)
async def me(user: CurrentUser) -> UserView:
    return UserView.of(user)


@router.get("/users", response_model=list[UserView], summary="List users (admin)")
async def list_users(admin: AdminUser, auth_service: AuthServiceDep) -> list[UserView]:
    users = await auth_service.list_users(admin)
    return [UserView.of(user) for user in users]


@router.put("/users/{user_id}/role", response_model=UserView, summary="Change a role (admin)")
async def set_role(
    user_id: str,
    payload: SetRoleRequest,
    admin: AdminUser,
    auth_service: AuthServiceDep,
) -> UserView:
    updated = await auth_service.set_role(admin, user_id, payload.role)
    return UserView.of(updated)
