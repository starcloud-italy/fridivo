"""Add Stripe subscription state and webhook idempotency.

Revision ID: 20260905_0006
Revises: 20260905_0005
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260905_0006"
down_revision = "20260905_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "households", sa.Column("stripe_customer_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "households",
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "households", sa.Column("subscription_status", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "households",
        sa.Column("subscription_current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "households",
        sa.Column("subscription_cancel_at_period_end", sa.Boolean(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_households_stripe_customer_id", "households", ["stripe_customer_id"]
    )
    op.create_unique_constraint(
        "uq_households_stripe_subscription_id", "households", ["stripe_subscription_id"]
    )
    op.create_table(
        "stripe_webhook_events",
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_stripe_webhook_events"),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_events")
    op.drop_constraint(
        "uq_households_stripe_subscription_id", "households", type_="unique"
    )
    op.drop_constraint("uq_households_stripe_customer_id", "households", type_="unique")
    op.drop_column("households", "subscription_cancel_at_period_end")
    op.drop_column("households", "subscription_current_period_end")
    op.drop_column("households", "subscription_status")
    op.drop_column("households", "stripe_subscription_id")
    op.drop_column("households", "stripe_customer_id")
