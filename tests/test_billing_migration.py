import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.session import engine


PREVIOUS_REVISION = "20260905_0005"
BILLING_REVISION = "20260905_0006"


def test_billing_migration_upgrade_and_downgrade():
    config = Config("alembic.ini")
    household_id = uuid.uuid4()

    try:
        command.downgrade(config, PREVIOUS_REVISION)
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert "stripe_webhook_events" not in inspector.get_table_names()
            columns = {column["name"] for column in inspector.get_columns("households")}
            assert "stripe_customer_id" not in columns

        command.upgrade(config, BILLING_REVISION)
        with engine.begin() as connection:
            inspector = inspect(connection)
            columns = {column["name"] for column in inspector.get_columns("households")}
            assert {
                "stripe_customer_id",
                "stripe_subscription_id",
                "subscription_status",
                "subscription_current_period_end",
                "subscription_cancel_at_period_end",
            }.issubset(columns)
            assert "stripe_webhook_events" in inspector.get_table_names()
            assert inspector.get_pk_constraint("stripe_webhook_events")[
                "constrained_columns"
            ] == ["event_id"]
            connection.execute(
                text(
                    "INSERT INTO stripe_webhook_events (event_id, event_type) "
                    "VALUES ('evt_migration', 'test.event')"
                )
            )
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM stripe_webhook_events "
                    "WHERE event_id = 'evt_migration'"
                )
            ) == 1
            connection.execute(
                text(
                    "INSERT INTO households "
                    "(id, name, country_code, default_language_code, currency_code, timezone, "
                    "stripe_customer_id, stripe_subscription_id) "
                    "VALUES (:id, 'Billing migration', 'IT', 'it', 'EUR', 'Europe/Rome', "
                    "'cus_unique', 'sub_unique')"
                ),
                {"id": household_id},
            )

        command.downgrade(config, PREVIOUS_REVISION)
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert "stripe_webhook_events" not in inspector.get_table_names()
            columns = {column["name"] for column in inspector.get_columns("households")}
            assert "stripe_customer_id" not in columns
            assert connection.scalar(
                text("SELECT count(*) FROM households WHERE id = :id"),
                {"id": household_id},
            ) == 1
    finally:
        command.upgrade(config, "head")
