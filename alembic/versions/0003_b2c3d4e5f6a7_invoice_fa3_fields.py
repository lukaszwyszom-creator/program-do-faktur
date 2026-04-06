"""invoice_fa3_fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-06

Dodaje pola wymagane przez FA(3):
- invoices.delivery_date       - data dostawy/wykonania uslugi (FA(3)/Fa/P_6)
- invoices.ksef_reference_number - numer KSeF po akceptacji faktury przez KSeF
"""

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("delivery_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("ksef_reference_number", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_invoices_ksef_reference_number",
        "invoices",
        ["ksef_reference_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_ksef_reference_number", table_name="invoices")
    op.drop_column("invoices", "ksef_reference_number")
    op.drop_column("invoices", "delivery_date")
