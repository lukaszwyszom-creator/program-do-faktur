"""invoice_fa3_type_correction

Adds invoice_type, correction_of_invoice_id, correction_of_ksef_number,
and correction_reason columns to the invoices table as required by KSeF FA(3)
compliance for correction invoices (KOR/KOR_ZAL/KOR_ROZ).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2025-06-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("invoice_type", sa.String(32), nullable=False, server_default="VAT"),
    )
    op.add_column(
        "invoices",
        sa.Column("correction_of_invoice_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("correction_of_ksef_number", sa.String(64), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("correction_reason", sa.String(512), nullable=True),
    )
    op.create_index("ix_invoices_invoice_type", "invoices", ["invoice_type"])


def downgrade() -> None:
    op.drop_index("ix_invoices_invoice_type", table_name="invoices")
    op.drop_column("invoices", "correction_reason")
    op.drop_column("invoices", "correction_of_ksef_number")
    op.drop_column("invoices", "correction_of_invoice_id")
    op.drop_column("invoices", "invoice_type")
