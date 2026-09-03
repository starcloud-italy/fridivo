from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.shopping import ShoppingListItem
from app.schemas.shopping import (
    ShoppingListItemCreate,
    ShoppingListItemStatusUpdate,
    ShoppingListItemUpdate,
)
from app.services.household import get_current_household


class HouseholdNotFoundError(Exception):
    pass


class ShoppingListItemNotFoundError(Exception):
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
