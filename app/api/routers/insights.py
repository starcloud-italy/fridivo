from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.insights import (
    ConsumptionInsightsRead,
    HouseholdOverviewRead,
    WasteWatchItemRead,
)
from app.services.consumption import HouseholdNotFoundError
from app.services.insights import (
    PlusPlanRequiredError,
    get_consumption_insights,
    get_household_overview,
    get_waste_watch,
)


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


@router.get("/waste-watch", response_model=list[WasteWatchItemRead])
def waste_watch(
    db: DbSession,
    current_user: CurrentUser,
) -> list[WasteWatchItemRead]:
    try:
        return get_waste_watch(db, current_user.id)
    except PlusPlanRequiredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PLUS plan required",
        ) from None
    except HouseholdNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Household not found",
        ) from None


@router.get("/overview", response_model=HouseholdOverviewRead)
def household_overview(
    db: DbSession,
    current_user: CurrentUser,
) -> HouseholdOverviewRead:
    try:
        return get_household_overview(db, current_user.id)
    except PlusPlanRequiredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PLUS plan required",
        ) from None
    except HouseholdNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Household not found",
        ) from None
