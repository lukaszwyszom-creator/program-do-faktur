"""payment_module

Revision ID: a1b2c3d4e5f6
Revises: 6462f591b285
Create Date: 2026-04-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f6"
down_revision = "6462f591b285"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- bank_transactions ---
    op.create_table(
        "bank_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("transaction_date", sa.Date, nullable=False),
        sa.Column("value_date", sa.Date, nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="PLN"),
        sa.Column("counterparty_name", sa.String(512), nullable=True),
        sa.Column("counterparty_account", sa.String(128), nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("match_status", sa.String(32), nullable=False, server_default="unmatched"),
        sa.Column("remaining_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("source_file", sa.String(512), nullable=True),
        sa.Column("raw_row_json", postgresql.JSONB, nullable=True),
        sa.Column("imported_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_transactions")),
    )
    op.create_index(op.f("ix_bank_transactions_external_id"), "bank_transactions", ["external_id"], unique=True)
    op.create_index(op.f("ix_bank_transactions_match_status"), "bank_transactions", ["match_status"])
    op.create_index(op.f("ix_bank_transactions_transaction_date"), "bank_transactions", ["transaction_date"])

    # --- payment_allocations ---
    op.create_table(
        "payment_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("allocated_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("match_method", sa.String(16), nullable=False),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("match_reasons_json", postgresql.JSONB, nullable=True),
        sa.Column("is_reversed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_allocations")),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["bank_transactions.id"],
            name=op.f("fk_payment_allocations_transaction_id_bank_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_payment_allocations_invoice_id_invoices"),
        ),
    )
    op.create_index(op.f("ix_payment_allocations_transaction_id"), "payment_allocations", ["transaction_id"])
    op.create_index(op.f("ix_payment_allocations_invoice_id"), "payment_allocations", ["invoice_id"])

    # --- add payment_status to invoices ---
    op.add_column(
        "invoices",
        sa.Column("payment_status", sa.String(32), nullable=False, server_default="unpaid"),
    )
    op.create_index(op.f("ix_invoices_payment_status"), "invoices", ["payment_status"])


def downgrade() -> None:
    # UWAGA — OPERACJA DESTRUKTYWNA:
    #   Poniższy downgrade TRWALE usuwa tabele bank_transactions i payment_allocations
    #   oraz kolumnę payment_status z invoices. Wszystkie dane płatności zostaną utracone.
    #   PRZED WYKONANIEM wykonaj pg_dump lub sprawdź, że nie ma danych produkcyjnych.
    op.drop_index(op.f("ix_invoices_payment_status"), table_name="invoices")
    op.drop_column("invoices", "payment_status")

    op.drop_index(op.f("ix_payment_allocations_invoice_id"), table_name="payment_allocations")
    op.drop_index(op.f("ix_payment_allocations_transaction_id"), table_name="payment_allocations")
    op.drop_table("payment_allocations")

    op.drop_index(op.f("ix_bank_transactions_transaction_date"), table_name="bank_transactions")
    op.drop_index(op.f("ix_bank_transactions_match_status"), table_name="bank_transactions")
    op.drop_index(op.f("ix_bank_transactions_external_id"), table_name="bank_transactions")
    op.drop_table("bank_transactions")
