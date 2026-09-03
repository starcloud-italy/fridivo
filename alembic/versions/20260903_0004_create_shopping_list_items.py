"""Create household shopping list items.

Revision ID: 20260903_0004
Revises: 20260902_0003
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260903_0004"
down_revision = "20260902_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_list_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_barcode", sa.String(length=14), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("is_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity IS NULL OR quantity > 0", name="ck_shopping_list_quantity_positive"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shopping_list_items_household_id", "shopping_list_items", ["household_id"])
    op.create_index(
        "ix_shopping_list_household_status_created",
        "shopping_list_items",
        ["household_id", "is_completed", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_shopping_list_household_status_created", table_name="shopping_list_items")
    op.drop_index("ix_shopping_list_items_household_id", table_name="shopping_list_items")
    op.drop_table("shopping_list_items")
