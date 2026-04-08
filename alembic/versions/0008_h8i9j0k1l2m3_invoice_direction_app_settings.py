"""invoice_direction_app_settings

Dwie niezależne zmiany schematu:
1. Kolumna ``direction`` (VARCHAR 8, NOT NULL, DEFAULT 'sale') w tabeli ``invoices``
   – umożliwia filtrowanie faktur sprzedaży kontra dokumentów zakupowych.
2. Tabela ``app_settings`` – singleton (id=1) przechowujący konfigurowalne
   parametry aplikacji (seller_nip, seller_name, …), które frontend może pobrać
   przez API zamiast trzymać wyłącznie w localStorage.

Revision ID: h8i9j0k1l2m3
Revises: f6a7b8c9d0e1
Create Date: 2026-04-07 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h8i9j0k1l2m3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. direction na tabeli invoices ───────────────────────────────────────
    op.add_column(
        "invoices",
        sa.Column(
            "direction",
            sa.String(8),
            nullable=False,
            server_default="sale",
        ),
    )
    op.create_index("ix_invoices_direction", "invoices", ["direction"])

    # ── 2. Tabela app_settings (singleton id=1) ───────────────────────────────
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("seller_nip", sa.String(10), nullable=True),
        sa.Column("seller_name", sa.String(256), nullable=True),
        sa.Column("seller_street", sa.String(256), nullable=True),
        sa.Column("seller_building_no", sa.String(32), nullable=True),
        sa.Column("seller_apartment_no", sa.String(32), nullable=True),
        sa.Column("seller_postal_code", sa.String(16), nullable=True),
        sa.Column("seller_city", sa.String(128), nullable=True),
        sa.Column("seller_country", sa.String(2), nullable=True, server_default="PL"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_invoices_direction", table_name="invoices")
    op.drop_column("invoices", "direction")
