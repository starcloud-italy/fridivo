from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.household import HouseholdPlan
from app.models.inventory import InventoryItem
from app.models.product import CatalogProduct
from app.models.shopping import ShoppingListItem
from app.schemas.shopping import (
    ShoppingListItemCreate,
    ShoppingListItemStatusUpdate,
    ShoppingListItemUpdate,
)
from app.services.household import get_current_household
from app.services.products import get_products_by_barcodes


class HouseholdNotFoundError(Exception):
    pass


class ShoppingListItemNotFoundError(Exception):
    pass


class PlusPlanRequiredError(Exception):
    pass


def _household_id_for_user(db: Session, user_id: UUID) -> UUID:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    return household.id


def _owned_item(db: Session, user_id: UUID, item_id: UUID) -> ShoppingListItem:
    household_id = _household_id_for_user(db, user_id)
    item = db.scalar(
        select(ShoppingListItem).where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.household_id == household_id,
        )
    )
    if item is None:
        raise ShoppingListItemNotFoundError
    return item


def _active_equivalent(
    db: Session,
    household_id: UUID,
    data: ShoppingListItemCreate,
) -> ShoppingListItem | None:
    statement = select(ShoppingListItem).where(
        ShoppingListItem.household_id == household_id,
        ShoppingListItem.is_completed.is_(False),
    )
    if data.product_barcode is not None:
        statement = statement.where(ShoppingListItem.product_barcode == data.product_barcode)
    else:
        statement = statement.where(
            ShoppingListItem.product_barcode.is_(None),
            func.lower(func.btrim(ShoppingListItem.name)) == data.name.casefold(),
        )
    return db.scalar(statement.order_by(ShoppingListItem.created_at, ShoppingListItem.id))


def create_shopping_list_item(
    db: Session,
    user_id: UUID,
    data: ShoppingListItemCreate,
) -> tuple[ShoppingListItem, bool]:
    household_id = _household_id_for_user(db, user_id)
    duplicate = _active_equivalent(db, household_id, data)
    if duplicate is not None:
        duplicate.quantity = (duplicate.quantity or 1) + (data.quantity or 1)
        if data.note is not None:
            duplicate.note = data.note
        db.commit()
        db.refresh(duplicate)
        return duplicate, False

    item = ShoppingListItem(
        household_id=household_id,
        product_barcode=data.product_barcode,
        name=data.name,
        quantity=data.quantity,
        note=data.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, True


def list_shopping_list_items(db: Session, user_id: UUID) -> list[ShoppingListItem]:
    household_id = _household_id_for_user(db, user_id)
    return list(
        db.scalars(
            select(ShoppingListItem)
            .where(ShoppingListItem.household_id == household_id)
            .order_by(
                ShoppingListItem.is_completed,
                ShoppingListItem.completed_at.desc().nulls_first(),
                ShoppingListItem.created_at.desc(),
                ShoppingListItem.id.desc(),
            )
        )
    )


def _shopping_suggestion_statement(household_id: UUID):
    latest_finished = (
        select(
            ConsumptionEvent.product_barcode.label("product_barcode"),
            func.max(ConsumptionEvent.occurred_at).label("last_finished_at"),
        )
        .where(
            ConsumptionEvent.household_id == household_id,
            ConsumptionEvent.event_type == ConsumptionEventType.FINISHED,
        )
        .group_by(ConsumptionEvent.product_barcode)
        .subquery()
    )
    currently_in_inventory = exists(
        select(InventoryItem.id).where(
            InventoryItem.household_id == household_id,
            InventoryItem.product_barcode == latest_finished.c.product_barcode,
        )
    )
    shopping_list_blocks_suggestion = exists(
        select(ShoppingListItem.id).where(
            ShoppingListItem.household_id == household_id,
            ShoppingListItem.product_barcode == latest_finished.c.product_barcode,
            or_(
                ShoppingListItem.is_completed.is_(False),
                and_(
                    ShoppingListItem.is_completed.is_(True),
                    ShoppingListItem.completed_at.is_not(None),
                    ShoppingListItem.completed_at >= latest_finished.c.last_finished_at,
                ),
            ),
        )
    )
    return (
        select(latest_finished.c.product_barcode, latest_finished.c.last_finished_at)
        .where(
            ~currently_in_inventory,
            ~shopping_list_blocks_suggestion,
        )
        .order_by(
            latest_finished.c.last_finished_at.desc(),
            latest_finished.c.product_barcode,
        )
    )


def _displayable_suggestion_products(db: Session, rows) -> dict[str, CatalogProduct]:
    products = get_products_by_barcodes(db, [row.product_barcode for row in rows])
    return {
        barcode: product
        for barcode, product in products.items()
        if product.name is not None and product.name.strip()
    }


def count_shopping_suggestion_candidates(db: Session, household_id: UUID) -> int:
    """Count every displayable Module 8 candidate, before its display limit."""
    rows = db.execute(_shopping_suggestion_statement(household_id)).all()
    return len(_displayable_suggestion_products(db, rows))


def list_shopping_suggestions(
    db: Session, user_id: UUID
) -> list[tuple[str, datetime, CatalogProduct]]:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    if household.plan != HouseholdPlan.PLUS:
        raise PlusPlanRequiredError

    rows = db.execute(_shopping_suggestion_statement(household.id).limit(5)).all()
    products = _displayable_suggestion_products(db, rows)
    return [
        (row.product_barcode, row.last_finished_at, product)
        for row in rows
        if (product := products.get(row.product_barcode)) is not None
        and product.name is not None
        and product.name.strip()
    ]


def update_shopping_list_item(
    db: Session,
    user_id: UUID,
    item_id: UUID,
    data: ShoppingListItemUpdate,
) -> ShoppingListItem:
    item = _owned_item(db, user_id, item_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field_name, value)
    db.commit()
    db.refresh(item)
    return item


def update_shopping_list_item_status(
    db: Session,
    user_id: UUID,
    item_id: UUID,
    data: ShoppingListItemStatusUpdate,
) -> ShoppingListItem:
    item = _owned_item(db, user_id, item_id)
    item.is_completed = data.is_completed
    item.completed_at = datetime.now(timezone.utc) if data.is_completed else None
    db.commit()
    db.refresh(item)
    return item


def delete_shopping_list_item(db: Session, user_id: UUID, item_id: UUID) -> None:
    item = _owned_item(db, user_id, item_id)
    db.delete(item)
    db.commit()
