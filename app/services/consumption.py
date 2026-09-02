from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.inventory import InventoryItem
from app.models.product import CatalogProduct
from app.schemas.consumption import ConsumptionEventCreate
from app.services.household import get_current_household
from app.services.products import get_product_by_barcode, get_products_by_barcodes


class HouseholdNotFoundError(Exception):
    pass


class InventoryItemNotFoundError(Exception):
    pass


class InsufficientInventoryQuantityError(Exception):
    pass


def _household_id_for_user(db: Session, user_id: UUID) -> UUID:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    return household.id


def create_consumption_event(
    db: Session,
    user_id: UUID,
    data: ConsumptionEventCreate,
) -> tuple[ConsumptionEvent, CatalogProduct | None]:
    household_id = _household_id_for_user(db, user_id)
    item = db.scalar(
        select(InventoryItem)
        .where(
            InventoryItem.id == data.inventory_item_id,
            InventoryItem.household_id == household_id,
        )
        .with_for_update()
    )
    if item is None:
        raise InventoryItemNotFoundError

    event_quantity = item.quantity if data.event_type == ConsumptionEventType.FINISHED else data.quantity
    if event_quantity is None or event_quantity > item.quantity:
        raise InsufficientInventoryQuantityError

    event = ConsumptionEvent(
        household_id=household_id,
        product_barcode=item.product_barcode,
        event_type=data.event_type,
        quantity=event_quantity,
    )
    db.add(event)

    remaining_quantity = item.quantity - event_quantity
    if remaining_quantity == 0:
        db.delete(item)
    else:
        item.quantity = remaining_quantity

    db.commit()
    db.refresh(event)
    return event, get_product_by_barcode(db, event.product_barcode)


def list_consumption_events(
    db: Session,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> list[tuple[ConsumptionEvent, CatalogProduct | None]]:
    household_id = _household_id_for_user(db, user_id)
    events = list(
        db.scalars(
            select(ConsumptionEvent)
            .where(ConsumptionEvent.household_id == household_id)
            .order_by(ConsumptionEvent.occurred_at.desc(), ConsumptionEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    products = get_products_by_barcodes(db, [event.product_barcode for event in events])
    return [(event, products.get(event.product_barcode)) for event in events]
