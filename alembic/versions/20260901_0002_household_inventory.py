"""Create household inventory items without modifying products.

Revision ID: 20260901_0002
Revises: 20260901_0001
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901_0002"
down_revision = "20260901_0001"
branch_labels = None
depends_on = None

storage_location = postgresql.ENUM(
    "fridge", "freezer", "pantry", "other", name="storage_location", create_type=False
)


def upgrade() -> None:
    storage_location.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "inventory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_barcode", sa.String(length=14), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("storage_location", storage_location, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_items_quantity_positive"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "product_barcode",
            name="uq_inventory_items_household_product",
        ),
    )
    op.create_index(
        "ix_inventory_items_household_id",
        "inventory_items",
        ["household_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_household_id", table_name="inventory_items")
    op.drop_table("inventory_items")
    storage_location.drop(op.get_bind(), checkfirst=True)

