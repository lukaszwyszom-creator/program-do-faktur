"""rename_product_sku_to_isbn

Zmiana nazwy kolumny products.sku → products.isbn

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-08 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("products", "sku", new_column_name="isbn")


def downgrade() -> None:
    op.alter_column("products", "isbn", new_column_name="sku")
