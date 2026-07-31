"""invoice_item_product_and_stock_movement_idempotency

- invoice_items.product_id → products.id (RESTRICT, nullable)
- stock_movements.invoice_item_id → invoice_items.id (SET NULL)
- unique (invoice_item_id, movement_type) for idempotent booking

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-07-31 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoice_items",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_invoice_items_product_id_products",
        "invoice_items",
        "products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_invoice_items_product_id", "invoice_items", ["product_id"])

    op.add_column(
        "stock_movements",
        sa.Column("invoice_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_movements_invoice_item_id",
        "stock_movements",
        "invoice_items",
        ["invoice_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_stock_movements_invoice_item_id", "stock_movements", ["invoice_item_id"])
    op.create_unique_constraint(
        "uq_stock_movement_invoice_item_type",
        "stock_movements",
        ["invoice_item_id", "movement_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_stock_movement_invoice_item_type", "stock_movements", type_="unique")
    op.drop_index("ix_stock_movements_invoice_item_id", table_name="stock_movements")
    op.drop_constraint("fk_stock_movements_invoice_item_id", "stock_movements", type_="foreignkey")
    op.drop_column("stock_movements", "invoice_item_id")

    op.drop_index("ix_invoice_items_product_id", table_name="invoice_items")
    op.drop_constraint("fk_invoice_items_product_id_products", "invoice_items", type_="foreignkey")
    op.drop_column("invoice_items", "product_id")
