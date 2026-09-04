from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.product import CatalogProduct


class ProductCatalogSchemaError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProductColumns:
    barcode: str
    name: str
    countries: str | None
    brands: str | None
    quantity: str | None
    categories: str | None
    image_url: str | None
    nutriscore_grade: str | None


_COLUMN_CANDIDATES = {
    "barcode": ("barcode", "code", "ean", "gtin"),
    "name": ("product_name", "name"),
    # OFF taxonomy tags are the least ambiguous representation when available.
    # Some local imports retain only the raw/localized `countries` field.
    "countries": ("countries_tags", "countries_en", "countries"),
    "brands": ("brands", "brand"),
    "quantity": ("quantity",),
    "categories": ("categories",),
    "image_url": ("image_url",),
    "nutriscore_grade": ("nutriscore_grade", "nutrition_grade_fr"),
}


def _first_available(available: set[str], candidates: tuple[str, ...]) -> str | None:
    return next((candidate for candidate in candidates if candidate in available), None)


@lru_cache(maxsize=16)
def _resolve_columns(database_url: str) -> ProductColumns:
    # Reflection is metadata-only and never mutates the external catalog table.
    from sqlalchemy import create_engine

    reflection_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        available = {
            column["name"] for column in inspect(reflection_engine).get_columns("products")
        }
    finally:
        reflection_engine.dispose()

    resolved = {
        field: _first_available(available, candidates)
        for field, candidates in _COLUMN_CANDIDATES.items()
    }
    if resolved["barcode"] is None or resolved["name"] is None:
        raise ProductCatalogSchemaError(
            "products must expose a text barcode column and a product name column"
        )
    return ProductColumns(**resolved)  # type: ignore[arg-type]


def _columns_for(db: Session) -> ProductColumns:
    bind = db.get_bind()
    if not isinstance(bind, Engine):
        bind = bind.engine
    return _resolve_columns(bind.url.render_as_string(hide_password=False))


def _quoted_projection(db: Session, columns: ProductColumns) -> tuple[str, str, str]:
    preparer = db.get_bind().dialect.identifier_preparer
    quote = preparer.quote

    def projected(column: str | None, alias: str) -> str:
        return f"{quote(column)} AS {quote(alias)}" if column else f"NULL AS {quote(alias)}"

    projection = ", ".join(
        (
            projected(columns.barcode, "barcode"),
            projected(columns.name, "name"),
            projected(columns.brands, "brands"),
            projected(columns.quantity, "quantity"),
            projected(columns.categories, "categories"),
            projected(columns.image_url, "image_url"),
            projected(columns.nutriscore_grade, "nutriscore_grade"),
        )
    )
    return projection, quote(columns.barcode), quote(columns.name)


def _to_product(row) -> CatalogProduct:
    values = row._mapping
    return CatalogProduct(
        barcode=str(values["barcode"]),
        name=values["name"],
        brands=values["brands"],
        quantity=values["quantity"],
        categories=values["categories"],
        image_url=values["image_url"],
        nutriscore_grade=values["nutriscore_grade"],
    )


def get_product_by_barcode(db: Session, barcode: str) -> CatalogProduct | None:
    columns = _columns_for(db)
    projection, barcode_column, _ = _quoted_projection(db, columns)
    statement = text(
        f"SELECT {projection} FROM products "
        f"WHERE {barcode_column} = :barcode LIMIT 1"
    )
    row = db.execute(statement, {"barcode": barcode}).first()
    return _to_product(row) if row is not None else None


def get_products_by_barcodes(
    db: Session, barcodes: list[str]
) -> dict[str, CatalogProduct]:
    if not barcodes:
        return {}
    columns = _columns_for(db)
    projection, barcode_column, _ = _quoted_projection(db, columns)
    statement = text(
        f"SELECT {projection} FROM products WHERE {barcode_column} IN :barcodes"
    ).bindparams(bindparam("barcodes", expanding=True))
    products = (_to_product(row) for row in db.execute(statement, {"barcodes": barcodes}))
    return {product.barcode: product for product in products}


def search_products(
    db: Session, query: str, *, limit: int, offset: int
) -> list[CatalogProduct]:
    columns = _columns_for(db)
    projection, barcode_column, name_column = _quoted_projection(db, columns)
    quote = db.get_bind().dialect.identifier_preparer.quote
    escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    if columns.countries:
        countries_expression = f"CAST({quote(columns.countries)} AS TEXT)"
        italy_rank = (
            f"CASE WHEN {countries_expression} ~* :italy_pattern THEN 0 ELSE 1 END"
        )
    else:
        italy_rank = "1"

    metadata_columns = (columns.brands, columns.quantity, columns.image_url)
    metadata_score = " + ".join(
        (
            f"CASE WHEN NULLIF(BTRIM(CAST({quote(column)} AS TEXT)), '') IS NOT NULL "
            "THEN 1 ELSE 0 END"
        )
        if column
        else "0"
        for column in metadata_columns
    )

    statement = text(
        f"SELECT {projection} FROM products "
        f"WHERE {name_column} ILIKE :pattern ESCAPE '\\' "
        "ORDER BY "
        f"CASE WHEN LOWER(BTRIM({name_column})) = LOWER(:query) THEN 0 "
        f"WHEN {name_column} ILIKE :prefix_pattern ESCAPE '\\' THEN 1 ELSE 2 END, "
        f"{italy_rank}, "
        f"({metadata_score}) DESC, "
        f"CHAR_LENGTH(BTRIM({name_column})) ASC, "
        f"LOWER({name_column}) ASC, {name_column} ASC, {barcode_column} ASC "
        "LIMIT :limit OFFSET :offset"
    )
    rows = db.execute(
        statement,
        {
            "query": query,
            "pattern": f"%{escaped_query}%",
            "prefix_pattern": f"{escaped_query}%",
            "italy_pattern": (
                r"(^|[^[:alnum:]])((en:)?italy|(it:)?italia)([^[:alnum:]]|$)"
            ),
            "limit": limit,
            "offset": offset,
        },
    )
    return [_to_product(row) for row in rows]
