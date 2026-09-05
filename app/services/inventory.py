from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.models.household import HouseholdPlan
from app.models.inventory import InventoryItem
from app.models.product import CatalogProduct
from app.schemas.inventory import ExpiryStatus, InventoryItemCreate, InventoryItemUpdate
from app.services.household import get_current_household
from app.services.products import get_product_by_barcode, get_products_by_barcodes


class HouseholdNotFoundError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


class InventoryItemNotFoundError(Exception):
    pass


class PlusPlanRequiredError(Exception):
    pass


def _household_id_for_user(db: Session, user_id: UUID) -> UUID:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    return household.id


def _owned_item(db: Session, user_id: UUID, item_id: UUID) -> InventoryItem:
    household_id = _household_id_for_user(db, user_id)
    item = db.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.household_id == household_id,
        )
    )
    if item is None:
        raise InventoryItemNotFoundError
    return item


def create_inventory_item(
    db: Session, user_id: UUID, data: InventoryItemCreate
) -> tuple[InventoryItem, CatalogProduct]:
    household_id = _household_id_for_user(db, user_id)
    product = get_product_by_barcode(db, data.product_barcode)
    if product is None:
        raise ProductNotFoundError

    insert_statement = postgresql_insert(InventoryItem).values(
        household_id=household_id,
        product_barcode=data.product_barcode,
        quantity=data.quantity,
        expiry_date=data.expiry_date,
        storage_location=data.storage_location,
    )
    statement = insert_statement.on_conflict_do_update(
        constraint="uq_inventory_items_household_product",
        set_={
            "quantity": InventoryItem.quantity + insert_statement.excluded.quantity,
            "expiry_date": func.coalesce(
                InventoryItem.expiry_date,
                insert_statement.excluded.expiry_date,
            ),
            "updated_at": func.now(),
        },
    ).returning(InventoryItem)
    item = db.scalars(statement).one()
    db.commit()
    db.refresh(item)
    return item, product


def list_inventory_items(
    db: Session, user_id: UUID
) -> list[tuple[InventoryItem, CatalogProduct | None]]:
    household_id = _household_id_for_user(db, user_id)
    items = list(
        db.scalars(
            select(InventoryItem)
            .where(InventoryItem.household_id == household_id)
            .order_by(InventoryItem.created_at, InventoryItem.id)
        )
    )
    products = get_products_by_barcodes(db, [item.product_barcode for item in items])
    return [(item, products.get(item.product_barcode)) for item in items]


def _today_for_household(timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


def _expiry_status(expiry_date: date, today: date) -> ExpiryStatus:
    days_until_expiry = (expiry_date - today).days
    if days_until_expiry < 0:
        return ExpiryStatus.EXPIRED
    if days_until_expiry == 0:
        return ExpiryStatus.TODAY
    if days_until_expiry == 1:
        return ExpiryStatus.TOMORROW
    return ExpiryStatus.FUTURE


def list_consume_first_items(
    db: Session, user_id: UUID
) -> list[tuple[InventoryItem, CatalogProduct | None, ExpiryStatus, int]]:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    if household.plan != HouseholdPlan.PLUS:
        raise PlusPlanRequiredError

    items = list(
        db.scalars(
            select(InventoryItem)
            .where(
                InventoryItem.household_id == household.id,
                InventoryItem.expiry_date.is_not(None),
            )
            .order_by(
                InventoryItem.expiry_date,
                InventoryItem.product_barcode,
                InventoryItem.id,
            )
            .limit(5)
        )
    )
    products = get_products_by_barcodes(db, [item.product_barcode for item in items])
    today = _today_for_household(household.timezone)
    return [
        (
            item,
            products.get(item.product_barcode),
            _expiry_status(item.expiry_date, today),
            (item.expiry_date - today).days,
        )
        for item in items
        if item.expiry_date is not None
    ]


def count_expiry_attention_items(db: Session, household_id: UUID) -> int:
    """Count every item eligible for Consume First, before its display limit."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(InventoryItem)
            .where(
                InventoryItem.household_id == household_id,
                InventoryItem.expiry_date.is_not(None),
            )
        )
        or 0
    )


def update_inventory_item(
    db: Session, user_id: UUID, item_id: UUID, data: InventoryItemUpdate
) -> tuple[InventoryItem, CatalogProduct | None]:
    item = _owned_item(db, user_id, item_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field_name, value)
    db.commit()
    db.refresh(item)
    return item, get_product_by_barcode(db, item.product_barcode)


def delete_inventory_item(db: Session, user_id: UUID, item_id: UUID) -> None:
    item = _owned_item(db, user_id, item_id)
    db.delete(item)
    db.commit()
