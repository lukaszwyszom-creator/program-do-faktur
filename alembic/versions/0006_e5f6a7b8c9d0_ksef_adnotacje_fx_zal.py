"""ksef_adnotacje_fx_zal

Adds Adnotacje flags (use_split_payment, self_billing, reverse_charge,
reverse_charge_art, reverse_charge_flag, cash_accounting_method),
foreign-currency fields (exchange_rate, exchange_rate_date),
advance fields (advance_amount, settled_advance_ids_json),
correction_type to invoices table;
vat_amount_pln to invoice_items;
nip column + composite index to ksef_sessions.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-06 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── invoices ──────────────────────────────────────────────────────
    op.add_column("invoices", sa.Column("correction_type", sa.String(32), nullable=True))

    # Adnotacje flags
    op.add_column("invoices", sa.Column("use_split_payment", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("invoices", sa.Column("self_billing", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("invoices", sa.Column("reverse_charge", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("invoices", sa.Column("reverse_charge_art", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("invoices", sa.Column("reverse_charge_flag", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("invoices", sa.Column("cash_accounting_method", sa.Boolean(), nullable=False, server_default="false"))

    # Foreign currency
    op.add_column("invoices", sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=True))
    op.add_column("invoices", sa.Column("exchange_rate_date", sa.Date(), nullable=True))

    # ZAL/ROZ
    op.add_column("invoices", sa.Column("advance_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("invoices", sa.Column("settled_advance_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # ── invoice_items ─────────────────────────────────────────────────
    op.add_column("invoice_items", sa.Column("vat_amount_pln", sa.Numeric(18, 2), nullable=True))

    # ── ksef_sessions ─────────────────────────────────────────────────
    # Add nip with temporary default, then make it non-nullable after backfill
    op.add_column("ksef_sessions", sa.Column("nip", sa.String(10), nullable=True))
    op.execute("UPDATE ksef_sessions SET nip = '0000000000' WHERE nip IS NULL")
    op.alter_column("ksef_sessions", "nip", nullable=False)
    op.create_index("ix_ksef_sessions_nip", "ksef_sessions", ["nip"])
    op.create_index("ix_ksef_sessions_nip_status", "ksef_sessions", ["nip", "status"])


def downgrade() -> None:
    op.drop_index("ix_ksef_sessions_nip_status", table_name="ksef_sessions")
    op.drop_index("ix_ksef_sessions_nip", table_name="ksef_sessions")
    op.drop_column("ksef_sessions", "nip")

    op.drop_column("invoice_items", "vat_amount_pln")

    op.drop_column("invoices", "settled_advance_ids_json")
    op.drop_column("invoices", "advance_amount")
    op.drop_column("invoices", "exchange_rate_date")
    op.drop_column("invoices", "exchange_rate")
    op.drop_column("invoices", "cash_accounting_method")
    op.drop_column("invoices", "reverse_charge_flag")
    op.drop_column("invoices", "reverse_charge_art")
    op.drop_column("invoices", "reverse_charge")
    op.drop_column("invoices", "self_billing")
    op.drop_column("invoices", "use_split_payment")
    op.drop_column("invoices", "correction_type")
