from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.insights import ConsumptionInsightsRead
from app.services.consumption import HouseholdNotFoundError
from app.services.insights import get_consumption_insights


router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/consumption", response_model=ConsumptionInsightsRead)
def consumption_insights(
    db: DbSession,
    current_user: CurrentUser,
) -> ConsumptionInsightsRead:
    try:
        return get_consumption_insights(db, current_user.id)
    except HouseholdNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Household not found",
        ) from None
