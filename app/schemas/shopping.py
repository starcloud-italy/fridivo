from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ShoppingListItemCreate(BaseModel):
    product_barcode: str | None = Field(default=None, min_length=8, max_length=14, pattern=r"^\d{8,14}$")
    name: str = Field(min_length=1, max_length=200)
    quantity: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None


class ShoppingListItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class ShoppingListItemStatusUpdate(BaseModel):
    is_completed: bool


class ShoppingListItemRead(BaseModel):
    id: UUID
    household_id: UUID
    product_barcode: str | None
    name: str
    quantity: int | None
    note: str | None
    is_completed: bool
    created_at: datetime
    completed_at: datetime | None
