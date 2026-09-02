from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.consumption import ConsumptionEvent
from app.models.product import CatalogProduct
from app.schemas.consumption import ConsumptionEventCreate, ConsumptionEventRead
from app.services.consumption import (
    HouseholdNotFoundError,
    InsufficientInventoryQuantityError,
    InventoryItemNotFoundError,
    create_consumption_event,
    list_consumption_events,
)

router = APIRouter(prefix="/consumption-events", tags=["consumption-events"])


def _response(event: ConsumptionEvent, product: CatalogProduct | None) -> ConsumptionEventRead:
    return ConsumptionEventRead(
        id=event.id,
        household_id=event.household_id,
        product_barcode=event.product_barcode,
        product_name=product.name if product else None,
        brands=product.brands if product else None,
        image_url=product.image_url if product else None,
        event_type=event.event_type,
        quantity=event.quantity,
        occurred_at=event.occurred_at,
    )


@router.post("", response_model=ConsumptionEventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    data: ConsumptionEventCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> ConsumptionEventRead:
    try:
        event, product = create_consumption_event(db, current_user.id, data)
    except (InventoryItemNotFoundError, HouseholdNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found") from None
    except InsufficientInventoryQuantityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quantity exceeds available inventory",
        ) from None
    return _response(event, product)


@router.get("", response_model=list[ConsumptionEventRead])
def list_events(
    db: DbSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConsumptionEventRead]:
    try:
        events = list_consumption_events(
            db,
            current_user.id,
            limit=limit,
            offset=offset,
        )
    except HouseholdNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found") from None
    return [_response(event, product) for event, product in events]
