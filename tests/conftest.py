import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://fridivo_test:test-only@localhost:5433/fridivo_test",
)
database_name = make_url(TEST_DATABASE_URL).database or ""
if not database_name.endswith("_test"):
    raise RuntimeError(
        "Refusing to run tests: TEST_DATABASE_URL must point to a database ending in '_test'"
    )

# Application configuration is fixed before importing the application modules.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET_KEY"] = "pytest-secret-key-never-use-in-production"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database():
    bootstrap_engine = create_engine(TEST_DATABASE_URL)
    with bootstrap_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS products "
                "(id BIGINT PRIMARY KEY, marker TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO products (id, marker) VALUES (-1, 'must-survive') "
                "ON CONFLICT (id) DO UPDATE SET marker = EXCLUDED.marker"
            )
        )

    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    yield
    bootstrap_engine.dispose()


@pytest.fixture(autouse=True)
def clean_managed_tables(migrated_test_database):
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM household_members"))
        connection.execute(text("DELETE FROM households"))
        connection.execute(text("DELETE FROM users"))


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def registration_payload() -> dict[str, str]:
    return {
        "email": "mario@example.com",
        "password": "correct-horse-battery-staple",
        "first_name": "Mario",
        "language_code": "it",
        "country_code": "IT",
        "household_name": "Casa Rossi",
        "currency_code": "EUR",
        "timezone": "Europe/Rome",
    }

