from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.inventory import InventoryItem
from app.models.product import CatalogProduct
from app.schemas.inventory import (
    ConsumeFirstItemRead,
    ExpiryStatus,
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
)
from app.services.inventory import (
    HouseholdNotFoundError,
    InventoryItemNotFoundError,
    PlusPlanRequiredError,
    ProductNotFoundError,
    create_inventory_item,
    delete_inventory_item,
    list_inventory_items,
    list_consume_first_items,
    update_inventory_item,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _response(item: InventoryItem, product: CatalogProduct | None) -> InventoryItemRead:
    return InventoryItemRead(
        id=item.id,
        household_id=item.household_id,
        product_barcode=item.product_barcode,
        quantity=item.quantity,
        expiry_date=item.expiry_date,
        storage_location=item.storage_location,
        product_name=product.name if product else None,
        brands=product.brands if product else None,
        product_quantity=product.quantity if product else None,
        image_url=product.image_url if product else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _consume_first_response(
    item: InventoryItem,
    product: CatalogProduct | None,
    expiry_status: ExpiryStatus,
    days_until_expiry: int,
) -> ConsumeFirstItemRead:
    return ConsumeFirstItemRead(
        **_response(item, product).model_dump(),
        expiry_status=expiry_status,
        days_until_expiry=days_until_expiry,
    )


def _translate_inventory_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProductNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if isinstance(exc, InventoryItemNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    if isinstance(exc, PlusPlanRequiredError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PLUS plan required")
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")


@router.post("", response_model=InventoryItemRead, status_code=status.HTTP_201_CREATED)
def create_item(
    data: InventoryItemCreate, db: DbSession, current_user: CurrentUser
) -> InventoryItemRead:
    try:
        item, product = create_inventory_item(db, current_user.id, data)
    except (ProductNotFoundError, HouseholdNotFoundError) as exc:
        raise _translate_inventory_error(exc) from None
    return _response(item, product)


@router.get("", response_model=list[InventoryItemRead])
def list_items(db: DbSession, current_user: CurrentUser) -> list[InventoryItemRead]:
    try:
        items = list_inventory_items(db, current_user.id)
    except HouseholdNotFoundError as exc:
        raise _translate_inventory_error(exc) from None
    return [_response(item, product) for item, product in items]


@router.get("/consume-first", response_model=list[ConsumeFirstItemRead])
def consume_first_items(
    db: DbSession, current_user: CurrentUser
) -> list[ConsumeFirstItemRead]:
    try:
        items = list_consume_first_items(db, current_user.id)
    except (HouseholdNotFoundError, PlusPlanRequiredError) as exc:
        raise _translate_inventory_error(exc) from None
    return [
        _consume_first_response(item, product, expiry_status, days_until_expiry)
        for item, product, expiry_status, days_until_expiry in items
    ]


@router.patch("/{item_id}", response_model=InventoryItemRead)
def update_item(
    item_id: UUID,
    data: InventoryItemUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> InventoryItemRead:
    try:
        item, product = update_inventory_item(db, current_user.id, item_id, data)
    except (InventoryItemNotFoundError, HouseholdNotFoundError) as exc:
        raise _translate_inventory_error(exc) from None
    return _response(item, product)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: UUID, db: DbSession, current_user: CurrentUser) -> Response:
    try:
        delete_inventory_item(db, current_user.id, item_id)
    except (InventoryItemNotFoundError, HouseholdNotFoundError) as exc:
        raise _translate_inventory_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
