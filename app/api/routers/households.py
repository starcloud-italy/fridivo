from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.household import HouseholdRead
from app.services.household import get_current_household

router = APIRouter(prefix="/households", tags=["households"])


@router.get("/current", response_model=HouseholdRead)
def current_household(db: DbSession, current_user: CurrentUser) -> HouseholdRead:
    result = get_current_household(db, current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No household found")
    household, membership = result
    return HouseholdRead.model_validate({**household.__dict__, "role": membership.role})

