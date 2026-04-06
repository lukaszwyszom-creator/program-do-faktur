"""transmission_upo

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-06

Dodaje pola do przechowywania UPO w tabeli transmissions:
- transmissions.upo_xml    - tresc UPO jako bytes (LargeBinary), nullable
- transmissions.upo_status - status pobrania: pending | fetched | failed, nullable
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transmissions",
        sa.Column("upo_xml", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "transmissions",
        sa.Column("upo_status", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transmissions", "upo_status")
    op.drop_column("transmissions", "upo_xml")
