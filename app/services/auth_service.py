from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import AuthenticatedUser, create_access_token, decode_access_token, hash_password, verify_password
from app.persistence.models.user import UserORM
from app.persistence.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse


class AuthService:
    def __init__(self, session: Session, user_repository: UserRepository) -> None:
        self.session = session
        self.user_repository = user_repository

    def login(self, username: str, password: str) -> TokenResponse:
        user = self.user_repository.get_by_username(username.strip())
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("Nieprawidlowy login lub haslo.")
        if not user.is_active:
            raise UnauthorizedError("Konto uzytkownika jest nieaktywne.")

        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            subject=str(user.id),
            expires_delta=expires_delta,
            additional_claims={"username": user.username, "role": user.role},
        )
        return TokenResponse(
            access_token=access_token,
            expires_in=int(expires_delta.total_seconds()),
            username=user.username,
            role=user.role,
        )

    def get_authenticated_user(self, token: str) -> AuthenticatedUser:
        try:
            payload = decode_access_token(token)
            user_id = payload["sub"]
        except Exception as exc:
            raise UnauthorizedError("Nieprawidlowy token dostepu.") from exc

        user = self.user_repository.get_by_id(UUID(user_id))
        if user is None or not user.is_active:
            raise UnauthorizedError("Uzytkownik nie istnieje lub jest nieaktywny.")

        return AuthenticatedUser(user_id=str(user.id), username=user.username, role=user.role)

    def bootstrap_initial_admin(self, username: str, password: str) -> UserORM | None:
        existing_user = self.user_repository.get_by_username(username)
        if existing_user is not None:
            return None

        user = UserORM(
            username=username,
            password_hash=hash_password(password),
            role="administrator",
            is_active=True,
        )
        self.user_repository.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user