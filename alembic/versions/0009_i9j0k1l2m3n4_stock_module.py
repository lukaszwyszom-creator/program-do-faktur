"""stock_module

Moduł magazynowy: products, warehouses, stock, stock_movements
+ domyślny magazyn (DEFAULT_WAREHOUSE_ID).

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-08 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None

DEFAULT_WAREHOUSE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ── 1. products ──────────────────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("unit", sa.String(32), nullable=False, server_default="szt"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)

    # ── 2. warehouses ────────────────────────────────────────────────────────
    op.create_table(
        "warehouses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Domyślny magazyn
    op.execute(
        f"""
        INSERT INTO warehouses (id, name, is_default)
        VALUES ('{DEFAULT_WAREHOUSE_ID}', 'Magazyn główny', true)
        """
    )

    # ── 3. stock ─────────────────────────────────────────────────────────────
    op.create_table(
        "stock",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.UniqueConstraint("product_id", "warehouse_id", name="uq_stock_product_warehouse"),
    )
    op.create_index("ix_stock_product_id", "stock", ["product_id"])
    op.create_index("ix_stock_warehouse_id", "stock", ["warehouse_id"])

    # ── 4. stock_movements ───────────────────────────────────────────────────
    op.create_table(
        "stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id"),
            nullable=False,
        ),
        sa.Column("movement_type", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_stock_movements_product_id", "stock_movements", ["product_id"])
    op.create_index("ix_stock_movements_warehouse_id", "stock_movements", ["warehouse_id"])
    op.create_index("ix_stock_movements_movement_type", "stock_movements", ["movement_type"])
    op.create_index("ix_stock_movements_invoice_id", "stock_movements", ["invoice_id"])
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])


def downgrade() -> None:
    op.drop_table("stock_movements")
    op.drop_table("stock")
    op.drop_table("warehouses")
    op.drop_table("products")
