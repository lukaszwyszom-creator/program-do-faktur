"""Utility helpers shared across the application."""
from __future__ import annotations

from uuid import UUID


def to_uuid(value: str | UUID | None) -> UUID | None:
    """Safely convert ``str | uuid.UUID | None`` → ``uuid.UUID | None``.

    Eliminates the ``'str' object has no attribute 'hex'`` error that
    SQLAlchemy raises when a bare string is stored into a
    ``UUID(as_uuid=True)`` column.

    Examples::

        to_uuid(None)          # → None
        to_uuid("abc-...-def") # → UUID("abc-...-def")
        to_uuid(some_uuid_obj) # → some_uuid_obj  (identity)
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
