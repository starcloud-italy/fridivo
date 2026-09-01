from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.product import ProductRead, ProductSearchResponse
from app.services.products import get_product_by_barcode, search_products

router = APIRouter(prefix="/products", tags=["products"])
BarcodePath = Annotated[
    str,
    Path(
        min_length=8,
        max_length=14,
        pattern=r"^\d{8,14}$",
        description="GTIN/EAN/UPC represented as text; leading zeroes are preserved",
    ),
]


def _product_or_404(db: DbSession, barcode: str) -> ProductRead:
    product = get_product_by_barcode(db, barcode)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductRead.model_validate(product)


@router.get("/search", response_model=ProductSearchResponse)
def search(
    db: DbSession,
    _current_user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductSearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Search query must contain at least two non-whitespace characters",
        )
    products = search_products(db, query, limit=limit, offset=offset)
    return ProductSearchResponse(items=products, limit=limit, offset=offset)


@router.get("/barcode/{barcode}", response_model=ProductRead)
def barcode_lookup(db: DbSession, _current_user: CurrentUser, barcode: BarcodePath) -> ProductRead:
    return _product_or_404(db, barcode)


@router.get("/{barcode}", response_model=ProductRead)
def product_detail(db: DbSession, _current_user: CurrentUser, barcode: BarcodePath) -> ProductRead:
    return _product_or_404(db, barcode)
