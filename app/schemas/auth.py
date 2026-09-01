from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserRead


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str | None = Field(default=None, max_length=100)
    language_code: str = Field(default="it", min_length=2, max_length=10)
    country_code: str = Field(default="IT", min_length=2, max_length=2)
    household_name: str | None = Field(default=None, min_length=1, max_length=150)
    currency_code: str = Field(default="EUR", min_length=3, max_length=3)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("country_code", "currency_code", mode="after")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.upper()

    @field_validator("language_code", mode="after")
    @classmethod
    def lowercase_language(cls, value: str) -> str:
        return value.lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    user: UserRead
    access_token: str
    token_type: str = "bearer"
