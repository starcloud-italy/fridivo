from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.shopping import ShoppingListItem
from app.schemas.shopping import (
    ShoppingListItemCreate,
    ShoppingListItemRead,
    ShoppingListItemStatusUpdate,
    ShoppingListItemUpdate,
    ShoppingSuggestionRead,
)
from app.services.shopping import (
    HouseholdNotFoundError,
    PlusPlanRequiredError,
    ShoppingListItemNotFoundError,
    create_shopping_list_item,
    delete_shopping_list_item,
    list_shopping_list_items,
    list_shopping_suggestions,
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


@router.get("/suggestions", response_model=list[ShoppingSuggestionRead])
def list_suggestions(
    db: DbSession, current_user: CurrentUser
) -> list[ShoppingSuggestionRead]:
    try:
        suggestions = list_shopping_suggestions(db, current_user.id)
    except PlusPlanRequiredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PLUS plan required",
        ) from None
    except HouseholdNotFoundError:
        raise _not_found() from None
    return [
        ShoppingSuggestionRead(
            product_barcode=barcode,
            product_name=product.name,
            brands=product.brands,
            product_quantity=product.quantity,
            image_url=product.image_url,
            last_finished_at=last_finished_at,
        )
        for barcode, last_finished_at, product in suggestions
    ]


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
