from pydantic import BaseModel, ConfigDict


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    barcode: str
    name: str | None
    brands: str | None
    quantity: str | None
    categories: str | None
    image_url: str | None
    nutriscore_grade: str | None


class ProductSearchResponse(BaseModel):
    items: list[ProductRead]
    limit: int
    offset: int

