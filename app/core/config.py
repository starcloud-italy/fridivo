from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    jwt_secret_key: str = Field(min_length=16, validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=30, gt=0, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    frontend_api_base_url: str = Field(default="", validation_alias="FRONTEND_API_BASE_URL")
    stripe_secret_key: SecretStr | None = Field(
        default=None, validation_alias="STRIPE_SECRET_KEY"
    )
    stripe_plus_monthly_price_id: str | None = Field(
        default=None, validation_alias="STRIPE_PLUS_MONTHLY_PRICE_ID"
    )
    stripe_webhook_secret: SecretStr | None = Field(
        default=None, validation_alias="STRIPE_WEBHOOK_SECRET"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
