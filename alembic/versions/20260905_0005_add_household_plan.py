"""Add the backend-controlled plan to households.

Revision ID: 20260905_0005
Revises: 20260903_0004
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260905_0005"
down_revision = "20260903_0004"
branch_labels = None
depends_on = None

household_plan = postgresql.ENUM(
    "FREE",
    "PLUS",
    name="household_plan",
    create_type=False,
)


def upgrade() -> None:
    household_plan.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "households",
        sa.Column(
            "plan",
            household_plan,
            server_default=sa.text("'FREE'::household_plan"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text("UPDATE households SET plan = 'FREE'::household_plan WHERE plan IS NULL")
    )
    op.alter_column("households", "plan", nullable=False)


def downgrade() -> None:
    op.drop_column("households", "plan")
    household_plan.drop(op.get_bind(), checkfirst=True)
