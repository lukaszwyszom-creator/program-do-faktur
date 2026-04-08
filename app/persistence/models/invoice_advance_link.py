"""M2M join table: InvoiceORM (ROZ) ↔ InvoiceORM (ZAL).

Zastępuje ``settled_advance_ids_json: JSONB`` na ``invoices``.
Kompozytowy PK (invoice_id, advance_invoice_id) zapewnia unikalność powiązań.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class InvoiceAdvanceLinkORM(Base):
    __tablename__ = "invoice_advance_links"

    # Faktura rozliczająca (ROZ) — właściciel linku
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Faktura zaliczkowa (ZAL) — rozliczana pozycja
    advance_invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        primary_key=True,
    )
