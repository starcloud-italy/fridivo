from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.household import HouseholdPlan, HouseholdRole


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    country_code: str
    default_language_code: str
    currency_code: str
    timezone: str
    plan: HouseholdPlan
    role: HouseholdRole
    created_at: datetime
    updated_at: datetime
