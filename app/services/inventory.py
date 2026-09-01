from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import InventoryItem
from app.models.product import CatalogProduct
from app.schemas.inventory import InventoryItemCreate, InventoryItemUpdate
from app.services.household import get_current_household
from app.services.products import get_product_by_barcode, get_products_by_barcodes


class HouseholdNotFoundError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


class InventoryItemNotFoundError(Exception):
    pass


class InventoryItemAlreadyExistsError(Exception):
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
    duplicate = db.scalar(
        select(InventoryItem.id).where(
            InventoryItem.household_id == household_id,
            InventoryItem.product_barcode == data.product_barcode,
        )
    )
    if duplicate is not None:
        raise InventoryItemAlreadyExistsError

    item = InventoryItem(
        household_id=household_id,
        product_barcode=data.product_barcode,
        quantity=data.quantity,
        expiry_date=data.expiry_date,
        storage_location=data.storage_location,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise InventoryItemAlreadyExistsError from exc
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

