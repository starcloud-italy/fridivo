from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    barcode: str
    name: str | None
    brands: str | None = None
    quantity: str | None = None
    categories: str | None = None
    image_url: str | None = None
    nutriscore_grade: str | None = None

