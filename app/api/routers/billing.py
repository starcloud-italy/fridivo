from fastapi import APIRouter, HTTPException, Request, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.household import HouseholdPlan
from app.schemas.billing import CheckoutSessionRead
from app.services.billing import (
    BillingConfigurationError,
    BillingProviderError,
    CheckoutReturnUrls,
    create_plus_checkout_session,
)
from app.services.household import get_current_household

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout", response_model=CheckoutSessionRead)
def create_checkout(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
) -> CheckoutSessionRead:
    result = get_current_household(db, current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No household found")
    household, _membership = result
    if household.plan != HouseholdPlan.FREE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Checkout is available only for FREE households",
        )

    app_url = str(request.url_for("frontend"))
    try:
        checkout_url = create_plus_checkout_session(
            household,
            current_user,
            CheckoutReturnUrls(
                success=f"{app_url}?checkout=success",
                cancel=f"{app_url}?checkout=cancel",
            ),
        )
    except BillingConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is temporarily unavailable",
        ) from None
    except BillingProviderError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Billing is temporarily unavailable",
        ) from None
    return CheckoutSessionRead(url=checkout_url)
