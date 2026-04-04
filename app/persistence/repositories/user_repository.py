from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models.user import UserORM


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: UUID) -> UserORM | None:
        return self.session.get(UserORM, user_id)

    def get_by_username(self, username: str) -> UserORM | None:
        query = select(UserORM).where(UserORM.username == username)
        return self.session.execute(query).scalar_one_or_none()

    def add(self, user: UserORM) -> UserORM:
        self.session.add(user)
        self.session.flush()
        return user
