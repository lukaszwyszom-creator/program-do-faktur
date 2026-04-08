"""ksef_hardening

Zmiany schematu dla hardeningu KSeF:
1. UNIQUE(idempotency_key) na tabeli transmissions
2. Tabela invoice_advance_links (M2M: invoices.id ↔ invoices.id)
3. Backfill z invoices.settled_advance_ids_json → invoice_advance_links
4. Drop invoices.settled_advance_ids_json

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-06 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. UNIQUE constraint na transmissions.idempotency_key ─────────
    # Najpierw usuń zduplikowane wartości (jeśli istnieją) — zachowując
    # najnowszy rekord dla każdego klucza.
    op.execute(
        """
        DELETE FROM transmissions
        WHERE id NOT IN (
            SELECT DISTINCT ON (idempotency_key) id
            FROM transmissions
            ORDER BY idempotency_key, created_at DESC
        )
        """
    )
    op.create_unique_constraint(
        "uq_transmissions_idempotency_key",
        "transmissions",
        ["idempotency_key"],
    )
    # Istniejący zwykły indeks ix_transmissions_idempotency_key staje się
    # redundantny wobec UNIQUE (który sam tworzy indeks); jeśli istnieje —
    # usuń go, aby nie duplikować.
    op.execute(
        """
        DROP INDEX IF EXISTS ix_transmissions_idempotency_key
        """
    )

    # ── 2. Tabela M2M: invoice_advance_links ──────────────────────────
    op.create_table(
        "invoice_advance_links",
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "advance_invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("invoice_id", "advance_invoice_id"),
    )

    # ── 3. Backfill: settled_advance_ids_json → invoice_advance_links ─
    # EXISTS guard: ignoruje UUID, które nie mają odpowiadającego wiersza
    # w invoices (usunięte lub stale dane), unikając ForeignKeyViolationError.
    op.execute(
        """
        INSERT INTO invoice_advance_links (invoice_id, advance_invoice_id)
        SELECT
            i.id AS invoice_id,
            elem::uuid AS advance_invoice_id
        FROM invoices i,
             jsonb_array_elements_text(i.settled_advance_ids_json) AS elem
        WHERE i.settled_advance_ids_json IS NOT NULL
          AND jsonb_array_length(i.settled_advance_ids_json) > 0
          AND EXISTS (
              SELECT 1 FROM invoices adv WHERE adv.id = elem::uuid
          )
        ON CONFLICT DO NOTHING
        """
    )

    # ── 4. Drop settled_advance_ids_json ──────────────────────────────
    op.drop_column("invoices", "settled_advance_ids_json")


def downgrade() -> None:
    # Przywroć JSONB column z server_default aby istniejące wiersze dostały []
    # zamiast NULL (zgodne z kontraktem aplikacji po rollbacku).
    op.add_column(
        "invoices",
        sa.Column(
            "settled_advance_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Backfill odwrotny: invoice_advance_links → settled_advance_ids_json
    op.execute(
        """
        UPDATE invoices i
        SET settled_advance_ids_json = sub.ids
        FROM (
            SELECT
                invoice_id,
                jsonb_agg(advance_invoice_id::text) AS ids
            FROM invoice_advance_links
            GROUP BY invoice_id
        ) sub
        WHERE i.id = sub.invoice_id
        """
    )

    op.drop_table("invoice_advance_links")

    # Przywróć zwykły indeks na idempotency_key (usuwa też UNIQUE)
    op.drop_constraint(
        "uq_transmissions_idempotency_key", "transmissions", type_="unique"
    )
    op.create_index(
        "ix_transmissions_idempotency_key", "transmissions", ["idempotency_key"]
    )
