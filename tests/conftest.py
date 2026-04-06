"""Wspólne fixture'y dla testów."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

# Ustawiamy zmienną ENV przed importem config aby uniknąć brakujących zmiennych
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-123")

from app.core.config import settings
from app.core.security import AuthenticatedUser
from app.domain.enums import InvoiceStatus
from app.domain.models.invoice import Invoice, InvoiceItem


# ---------------------------------------------------------------------------
# Settings override helper
# ---------------------------------------------------------------------------

@contextmanager
def _patch_settings(**kwargs: Any):
    """Context manager – safely override frozen Settings fields.

    Uses ``object.__setattr__`` to bypass Pydantic's immutability.
    Restores originals on exit, even if the test raises.

    Usage::

        with _patch_settings(seller_nip="1234567890", seller_name="Test"):
            ...
    """
    original = {k: getattr(settings, k) for k in kwargs}
    try:
        for k, v in kwargs.items():
            object.__setattr__(settings, k, v)
        yield settings
    finally:
        for k, v in original.items():
            object.__setattr__(settings, k, v)


@pytest.fixture()
def override_settings():
    """Fixture zwracający context manager do bezpiecznego nadpisywania Settings.

    Example::

        def test_something(override_settings):
            with override_settings(seller_nip="9999999999"):
                ...
    """
    return _patch_settings


@pytest.fixture()
def actor() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=str(uuid4()),
        username="testuser",
        role="administrator",
    )


@pytest.fixture()
def sample_invoice_item() -> InvoiceItem:
    return InvoiceItem(
        id=uuid4(),
        name="Usługa programistyczna",
        quantity=Decimal("10"),
        unit="godz.",
        unit_price_net=Decimal("200.00"),
        vat_rate=Decimal("23"),
        net_total=Decimal("2000.00"),
        vat_total=Decimal("460.00"),
        gross_total=Decimal("2460.00"),
        sort_order=1,
    )


@pytest.fixture()
def sample_invoice(sample_invoice_item: InvoiceItem) -> Invoice:
    now = datetime.now(UTC)
    return Invoice(
        id=uuid4(),
        number_local=None,
        status=InvoiceStatus.DRAFT,
        issue_date=date(2026, 4, 5),
        sale_date=date(2026, 4, 5),
        currency="PLN",
        seller_snapshot={"nip": "1234567890", "name": "Sprzedawca"},
        buyer_snapshot={"nip": "0987654321", "name": "Nabywca"},
        items=[sample_invoice_item],
        total_net=Decimal("2000.00"),
        total_vat=Decimal("460.00"),
        total_gross=Decimal("2460.00"),
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def mock_session() -> MagicMock:
    session = MagicMock()
    session.begin.return_value.__enter__ = MagicMock(return_value=None)
    session.begin.return_value.__exit__ = MagicMock(return_value=False)
    return session
