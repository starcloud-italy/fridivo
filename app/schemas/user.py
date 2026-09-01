from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    first_name: str | None
    language_code: str
    country_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

