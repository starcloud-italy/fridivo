from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.consumption import ConsumptionEventType


class ConsumptionEventCreate(BaseModel):
    inventory_item_id: UUID
    event_type: ConsumptionEventType
    quantity: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_quantity_semantics(self) -> Self:
        if self.event_type in {ConsumptionEventType.CONSUMED, ConsumptionEventType.DISCARDED}:
            if self.quantity is None:
                raise ValueError("quantity is required for consumed and discarded events")
        elif self.quantity is not None:
            raise ValueError("quantity must be omitted for finished events")
        return self


class ConsumptionEventRead(BaseModel):
    id: UUID
    household_id: UUID
    product_barcode: str
    product_name: str | None
    brands: str | None
    image_url: str | None
    event_type: ConsumptionEventType
    quantity: int
    occurred_at: datetime
