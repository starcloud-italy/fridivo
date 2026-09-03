from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.shopping import ShoppingListItem
from app.schemas.shopping import (
    ShoppingListItemCreate,
    ShoppingListItemRead,
    ShoppingListItemStatusUpdate,
    ShoppingListItemUpdate,
)
from app.services.shopping import (
    HouseholdNotFoundError,
    ShoppingListItemNotFoundError,
    create_shopping_list_item,
    delete_shopping_list_item,
    list_shopping_list_items,
    update_shopping_list_item,
    update_shopping_list_item_status,
)


router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shopping list item not found")


def _response(item: ShoppingListItem) -> ShoppingListItemRead:
    return ShoppingListItemRead.model_validate(item, from_attributes=True)


@router.post("", response_model=ShoppingListItemRead)
def create_item(
    data: ShoppingListItemCreate,
    db: DbSession,
    current_user: CurrentUser,
    response: Response,
) -> ShoppingListItemRead:
    try:
        item, created = create_shopping_list_item(db, current_user.id, data)
    except HouseholdNotFoundError:
        raise _not_found() from None
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(item)


@router.get("", response_model=list[ShoppingListItemRead])
def list_items(db: DbSession, current_user: CurrentUser) -> list[ShoppingListItemRead]:
    try:
        items = list_shopping_list_items(db, current_user.id)
    except HouseholdNotFoundError:
        raise _not_found() from None
    return [_response(item) for item in items]


@router.patch("/{item_id}", response_model=ShoppingListItemRead)
def update_item(
    item_id: UUID,
    data: ShoppingListItemUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> ShoppingListItemRead:
    try:
        return _response(update_shopping_list_item(db, current_user.id, item_id, data))
    except (ShoppingListItemNotFoundError, HouseholdNotFoundError):
        raise _not_found() from None


@router.patch("/{item_id}/status", response_model=ShoppingListItemRead)
def update_item_status(
    item_id: UUID,
    data: ShoppingListItemStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> ShoppingListItemRead:
    try:
        return _response(update_shopping_list_item_status(db, current_user.id, item_id, data))
    except (ShoppingListItemNotFoundError, HouseholdNotFoundError):
        raise _not_found() from None


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: UUID, db: DbSession, current_user: CurrentUser) -> Response:
    try:
        delete_shopping_list_item(db, current_user.id, item_id)
    except (ShoppingListItemNotFoundError, HouseholdNotFoundError):
        raise _not_found() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
