from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.household import HouseholdRole


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    country_code: str
    default_language_code: str
    currency_code: str
    timezone: str
    role: HouseholdRole
    created_at: datetime
    updated_at: datetime

