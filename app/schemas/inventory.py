import enum
from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.inventory import StorageLocation


class InventoryItemCreate(BaseModel):
    product_barcode: str = Field(min_length=8, max_length=14, pattern=r"^\d{8,14}$")
    quantity: int = Field(gt=0)
    expiry_date: date | None = None
    storage_location: StorageLocation


class InventoryItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    expiry_date: date | None = None
    storage_location: StorageLocation | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in ("quantity", "storage_location"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class InventoryItemRead(BaseModel):
    id: UUID
    household_id: UUID
    product_barcode: str
    quantity: int
    expiry_date: date | None
    storage_location: StorageLocation
    product_name: str | None
    brands: str | None
    product_quantity: str | None
    image_url: str | None
    created_at: datetime
    updated_at: datetime


class ExpiryStatus(str, enum.Enum):
    EXPIRED = "EXPIRED"
    TODAY = "TODAY"
    TOMORROW = "TOMORROW"
    FUTURE = "FUTURE"


class ConsumeFirstItemRead(InventoryItemRead):
    expiry_date: date
    expiry_status: ExpiryStatus
    days_until_expiry: int
