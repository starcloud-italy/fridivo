"""Create durable household consumption events.

Revision ID: 20260902_0003
Revises: 20260901_0002
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260902_0003"
down_revision = "20260901_0002"
branch_labels = None
depends_on = None

consumption_event_type = postgresql.ENUM(
    "CONSUMED",
    "FINISHED",
    "DISCARDED",
    name="consumption_event_type",
    create_type=False,
)


def upgrade() -> None:
    consumption_event_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "consumption_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_barcode", sa.String(length=14), nullable=False),
        sa.Column("event_type", consumption_event_type, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_consumption_events_quantity_positive"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consumption_events_household_id",
        "consumption_events",
        ["household_id"],
        unique=False,
    )
    op.create_index(
        "ix_consumption_events_household_occurred_at",
        "consumption_events",
        ["household_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_consumption_events_household_occurred_at", table_name="consumption_events")
    op.drop_index("ix_consumption_events_household_id", table_name="consumption_events")
    op.drop_table("consumption_events")
    consumption_event_type.drop(op.get_bind(), checkfirst=True)
