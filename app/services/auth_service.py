"""Authentication and user management.

Argon2id rather than bcrypt: bcrypt silently truncates at 72 bytes, which turns a long
passphrase into a weaker secret than the user believes they chose. Argon2 also lets the cost
parameters move with hardware without changing the stored format.

Tokens are stateless JWTs. That is the right trade for this application: there is no logout-
everywhere requirement, and the alternative is a session lookup on every request. The honest
consequence is that a token stays valid until it expires, which is recorded in
docs/backlog.md.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import func, select

from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.models import Role
from app.domain.rbac import can_manage_users
from app.infra.db import Database
from app.infra.models import User
from app.settings import Settings

MIN_PASSWORD_LENGTH = 8


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The caller's identity, as resolved from a bearer token."""

    id: str
    email: str
    display_name: str
    role: Role
    is_demo: bool

    @classmethod
    def from_row(cls, row: User) -> AuthenticatedUser:
        return cls(
            id=row.id,
            email=row.email,
            display_name=row.display_name,
            role=Role(row.role),
            is_demo=row.is_demo,
        )


@dataclass(frozen=True, slots=True)
class IssuedToken:
    access_token: str
    expires_at: datetime
    # The OAuth scheme name, not a credential.
    token_type: str = "bearer"  # noqa: S105


class AuthService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings
        # Defaults are the argon2-cffi recommendations; tuning them is a deployment concern.
        self._hasher = PasswordHasher()

    # --- password handling --------------------------------------------------------

    def hash_password(self, password: str) -> str:
        self._validate_password(password)
        return self._hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"The password must be at least {MIN_PASSWORD_LENGTH} characters."
            )

    # --- tokens ------------------------------------------------------------------

    def issue_token(self, user: User | AuthenticatedUser) -> IssuedToken:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self._settings.access_token_ttl_minutes)
        role = user.role if isinstance(user.role, str) else user.role.value
        payload: dict[str, Any] = {
            "sub": user.id,
            "email": user.email,
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(
            payload,
            self._settings.jwt_secret.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
        )
        return IssuedToken(access_token=token, expires_at=expires_at)

    def decode_token(self, token: str) -> str:
        """Return the user id in the token, or raise AuthenticationError.

        The algorithm is pinned to the configured one. Accepting whatever the token's header
        claims is the classic JWT confusion bug, where an attacker downgrades to "none".
        """
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret.get_secret_value(),
                algorithms=[self._settings.jwt_algorithm],
                options={"require": ["exp", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("The session has expired. Sign in again.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("The access token is not valid.") from exc

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("The access token carries no subject.")
        return subject

    # --- user lifecycle ----------------------------------------------------------

    async def sign_up(
        self, email: str, password: str, display_name: str, role: Role = Role.ANALYST
    ) -> tuple[AuthenticatedUser, IssuedToken]:
        normalised = self._normalise_email(email)
        password_hash = self.hash_password(password)

        async with self._database.session() as session:
            existing = await session.scalar(select(User).where(User.email == normalised))
            if existing is not None:
                raise ConflictError("An account with that email already exists.")
            row = User(
                email=normalised,
                display_name=display_name.strip() or normalised.split("@")[0],
                password_hash=password_hash,
                role=role.value,
            )
            session.add(row)
            await session.flush()
            user = AuthenticatedUser.from_row(row)
        return user, self.issue_token(user)

    async def sign_in(self, email: str, password: str) -> tuple[AuthenticatedUser, IssuedToken]:
        normalised = self._normalise_email(email)
        async with self._database.read_session() as session:
            row = await session.scalar(select(User).where(User.email == normalised))

        # The same message and a hash computation on both paths, so a wrong email and a wrong
        # password are indistinguishable in both response body and response time.
        if row is None:
            self._hasher.hash(password)
            raise AuthenticationError("That email and password combination is not recognised.")
        if not self.verify_password(password, row.password_hash):
            raise AuthenticationError("That email and password combination is not recognised.")

        user = AuthenticatedUser.from_row(row)
        return user, self.issue_token(user)

    async def sign_in_demo(self, role: Role) -> tuple[AuthenticatedUser, IssuedToken]:
        """One-click sign-in for the seeded demo accounts.

        Restricted to rows flagged `is_demo`, so this can never become a way into a real
        account even if someone points it at a production database.
        """
        async with self._database.read_session() as session:
            row = await session.scalar(
                select(User).where(User.is_demo.is_(True), User.role == role.value)
            )
        if row is None:
            raise NotFoundError(f"No demo {role.value} account exists. Run: .\\tasks.ps1 seed")
        user = AuthenticatedUser.from_row(row)
        return user, self.issue_token(user)

    async def resolve_token(self, token: str) -> AuthenticatedUser:
        user_id = self.decode_token(token)
        async with self._database.read_session() as session:
            row = await session.get(User, user_id)
        # The token may outlive the account it names, so the row is checked, not just the claim.
        if row is None:
            raise AuthenticationError("The account on this token no longer exists.")
        return AuthenticatedUser.from_row(row)

    async def list_users(self, actor: AuthenticatedUser) -> list[AuthenticatedUser]:
        if not can_manage_users(actor.role):
            raise PermissionDeniedError("Only an admin may list users.")
        async with self._database.read_session() as session:
            rows = (await session.scalars(select(User).order_by(User.created_at))).all()
        return [AuthenticatedUser.from_row(row) for row in rows]

    async def set_role(
        self, actor: AuthenticatedUser, user_id: str, role: Role
    ) -> AuthenticatedUser:
        if not can_manage_users(actor.role):
            raise PermissionDeniedError("Only an admin may change roles.")
        async with self._database.session() as session:
            row = await session.get(User, user_id)
            if row is None:
                raise NotFoundError("That user does not exist.")
            if row.id == actor.id and role is not Role.ADMIN:
                # Without this an admin can lock every administrator out of the deployment.
                raise ValidationError("An admin cannot remove their own admin role.")
            row.role = role.value
            await session.flush()
            return AuthenticatedUser.from_row(row)

    async def count_users(self) -> int:
        async with self._database.read_session() as session:
            return await session.scalar(select(func.count()).select_from(User)) or 0

    @staticmethod
    def new_share_token() -> str:
        """An unguessable token for read-only report sharing."""
        return secrets.token_urlsafe(24)

    @staticmethod
    def _normalise_email(email: str) -> str:
        cleaned = email.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValidationError("That does not look like an email address.")
        return cleaned
