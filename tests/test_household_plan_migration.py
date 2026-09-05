import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.session import engine


PREVIOUS_REVISION = "20260903_0004"
PLAN_REVISION = "20260905_0005"


def test_household_plan_migration_upgrade_and_downgrade():
    config = Config("alembic.ini")
    legacy_household_id = uuid.uuid4()

    try:
        command.downgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO households "
                    "(id, name, country_code, default_language_code, currency_code, timezone) "
                    "VALUES (:id, 'Legacy household', 'IT', 'it', 'EUR', 'Europe/Rome')"
                ),
                {"id": legacy_household_id},
            )

        command.upgrade(config, PLAN_REVISION)
        with engine.connect() as connection:
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("households")
            }
            assert columns["plan"]["nullable"] is False
            assert connection.scalar(
                text("SELECT plan::text FROM households WHERE id = :id"),
                {"id": legacy_household_id},
            ) == "FREE"
            default_plan = connection.scalar(
                text(
                    "INSERT INTO households "
                    "(id, name, country_code, default_language_code, currency_code, timezone) "
                    "VALUES (:id, 'Default household', 'IT', 'it', 'EUR', 'Europe/Rome') "
                    "RETURNING plan::text"
                ),
                {"id": uuid.uuid4()},
            )
            assert default_plan == "FREE"

        command.downgrade(config, PREVIOUS_REVISION)
        with engine.connect() as connection:
            column_names = {
                column["name"] for column in inspect(connection).get_columns("households")
            }
            assert "plan" not in column_names
            assert connection.scalar(
                text("SELECT count(*) FROM households WHERE id = :id"),
                {"id": legacy_household_id},
            ) == 1
    finally:
        command.upgrade(config, "head")
