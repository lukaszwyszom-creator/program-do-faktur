from dataclasses import dataclass
from uuid import UUID

from app.domain.enums import UserRole


@dataclass(slots=True)
class User:
    id: UUID
    username: str
    role: UserRole
    is_active: bool
