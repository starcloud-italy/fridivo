from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.models.household import HouseholdPlan
from app.schemas.insights import (
    ConsumptionInsightPeriod,
    ConsumptionInsightsRead,
    ConsumptionInsightSummary,
    HouseholdOverviewRead,
    ProductConsumptionInsight,
    WasteWatchItemRead,
)
from app.services.consumption import HouseholdNotFoundError
from app.services.household import get_current_household
from app.services.inventory import count_expiry_attention_items
from app.services.products import get_products_by_barcodes
from app.services.shopping import count_shopping_suggestion_candidates


INSIGHT_PERIOD_DAYS = 30
RANKING_LIMIT = 5
USED_EVENT_TYPES = (ConsumptionEventType.CONSUMED, ConsumptionEventType.FINISHED)


class PlusPlanRequiredError(Exception):
    pass


def _waste_ratio(consumed_quantity: int, discarded_quantity: int) -> float | None:
    total = consumed_quantity + discarded_quantity
    return discarded_quantity / total if total else None


def _consumption_aggregates(
    db: Session,
    household_id: UUID,
    period_start: datetime,
    period_end: datetime,
):
    used_quantity = func.coalesce(
        func.sum(
            case(
                (
                    ConsumptionEvent.event_type.in_(USED_EVENT_TYPES),
                    ConsumptionEvent.quantity,
                ),
                else_=0,
            )
        ),
        0,
    ).label("consumed_quantity")
    discarded_quantity = func.coalesce(
        func.sum(
            case(
                (
                    ConsumptionEvent.event_type == ConsumptionEventType.DISCARDED,
                    ConsumptionEvent.quantity,
                ),
                else_=0,
            )
        ),
        0,
    ).label("discarded_quantity")
    return list(
        db.execute(
            select(
                ConsumptionEvent.product_barcode,
                used_quantity,
                discarded_quantity,
                func.count()
                .filter(ConsumptionEvent.event_type == ConsumptionEventType.CONSUMED)
                .label("consumed_event_count"),
                func.count()
                .filter(ConsumptionEvent.event_type == ConsumptionEventType.FINISHED)
                .label("finished_event_count"),
                func.count()
                .filter(ConsumptionEvent.event_type == ConsumptionEventType.DISCARDED)
                .label("discarded_event_count"),
            )
            .where(
                ConsumptionEvent.household_id == household_id,
                ConsumptionEvent.occurred_at >= period_start,
                ConsumptionEvent.occurred_at <= period_end,
            )
            .group_by(ConsumptionEvent.product_barcode)
        )
    )


def _consumption_summary(aggregates) -> ConsumptionInsightSummary:
    consumed = sum(int(row.consumed_quantity) for row in aggregates)
    discarded = sum(int(row.discarded_quantity) for row in aggregates)
    return ConsumptionInsightSummary(
        consumed_quantity=consumed,
        discarded_quantity=discarded,
        consumed_event_count=sum(int(row.consumed_event_count) for row in aggregates),
        finished_event_count=sum(int(row.finished_event_count) for row in aggregates),
        discarded_event_count=sum(int(row.discarded_event_count) for row in aggregates),
        distinct_products=len(aggregates),
        waste_ratio=_waste_ratio(consumed, discarded),
    )


def get_consumption_insights(
    db: Session,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> ConsumptionInsightsRead:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    household_id = household.id
    period_start, period_end = _insight_period(household.timezone, now)

    aggregates = _consumption_aggregates(
        db,
        household_id,
        period_start,
        period_end,
    )

    latest_events = {
        event.product_barcode: event
        for event in db.scalars(
            select(ConsumptionEvent)
            .where(
                ConsumptionEvent.household_id == household_id,
                ConsumptionEvent.occurred_at >= period_start,
                ConsumptionEvent.occurred_at <= period_end,
            )
            .distinct(ConsumptionEvent.product_barcode)
            .order_by(
                ConsumptionEvent.product_barcode,
                ConsumptionEvent.occurred_at.desc(),
                ConsumptionEvent.id.desc(),
            )
        )
    }
    catalog = get_products_by_barcodes(
        db, [row.product_barcode for row in aggregates]
    )

    products: list[ProductConsumptionInsight] = []
    for row in aggregates:
        latest = latest_events[row.product_barcode]
        product = catalog.get(row.product_barcode)
        consumed = int(row.consumed_quantity)
        discarded = int(row.discarded_quantity)
        products.append(
            ProductConsumptionInsight(
                barcode=row.product_barcode,
                product_name=product.name if product else None,
                brands=product.brands if product else None,
                image_url=product.image_url if product else None,
                consumed_quantity=consumed,
                discarded_quantity=discarded,
                consumed_event_count=int(row.consumed_event_count),
                finished_event_count=int(row.finished_event_count),
                discarded_event_count=int(row.discarded_event_count),
                last_event=latest.event_type,
                last_event_at=latest.occurred_at,
                waste_ratio=_waste_ratio(consumed, discarded),
            )
        )

    products.sort(key=lambda item: item.barcode)
    summary = _consumption_summary(aggregates)
    most_consumed = sorted(
        (item for item in products if item.consumed_quantity > 0),
        key=lambda item: (-item.consumed_quantity, item.barcode),
    )[:RANKING_LIMIT]
    most_discarded = sorted(
        (item for item in products if item.discarded_quantity > 0),
        key=lambda item: (-item.discarded_quantity, item.barcode),
    )[:RANKING_LIMIT]

    return ConsumptionInsightsRead(
        period=ConsumptionInsightPeriod(
            days=INSIGHT_PERIOD_DAYS,
            start=period_start,
            end=period_end,
        ),
        summary=summary,
        most_consumed=most_consumed,
        most_discarded=most_discarded,
        products=products,
    )


def _household_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _insight_period(
    timezone_name: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    household_timezone = _household_timezone(timezone_name)
    if now is None:
        period_end = datetime.now(household_timezone)
    elif now.tzinfo is None:
        period_end = now.replace(tzinfo=household_timezone)
    else:
        period_end = now.astimezone(household_timezone)
    return period_end - timedelta(days=INSIGHT_PERIOD_DAYS), period_end


def _waste_watch_period(
    timezone_name: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Backward-compatible Module 9 name for the shared Insights period."""
    return _insight_period(timezone_name, now)


def _waste_watch_rows(
    db: Session,
    household_id: UUID,
    period_start: datetime,
    period_end: datetime,
    *,
    limit: int | None = None,
):
    discarded_event_count = func.count(ConsumptionEvent.id).label(
        "discarded_event_count"
    )
    discarded_quantity = func.sum(ConsumptionEvent.quantity).label(
        "discarded_quantity"
    )
    last_discarded_at = func.max(ConsumptionEvent.occurred_at).label(
        "last_discarded_at"
    )
    statement = (
        select(
            ConsumptionEvent.product_barcode,
            discarded_event_count,
            discarded_quantity,
            last_discarded_at,
        )
        .where(
            ConsumptionEvent.household_id == household_id,
            ConsumptionEvent.event_type == ConsumptionEventType.DISCARDED,
            ConsumptionEvent.occurred_at >= period_start,
            ConsumptionEvent.occurred_at <= period_end,
        )
        .group_by(ConsumptionEvent.product_barcode)
        .having(func.count(ConsumptionEvent.id) >= 2)
        .order_by(
            discarded_event_count.desc(),
            discarded_quantity.desc(),
            last_discarded_at.desc(),
            ConsumptionEvent.product_barcode,
        )
    )
    if limit is not None:
        statement = statement.limit(limit)
    return db.execute(statement).all()


def _displayable_waste_products(db: Session, rows):
    catalog = get_products_by_barcodes(db, [row.product_barcode for row in rows])
    return {
        barcode: product
        for barcode, product in catalog.items()
        if product.name is not None and product.name.strip()
    }


def count_repeated_waste_products(
    db: Session,
    household_id: UUID,
    period_start: datetime,
    period_end: datetime,
) -> int:
    """Count every displayable Module 9 pattern, before its display limit."""
    rows = _waste_watch_rows(db, household_id, period_start, period_end)
    return len(_displayable_waste_products(db, rows))


def get_waste_watch(
    db: Session,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> list[WasteWatchItemRead]:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    if household.plan != HouseholdPlan.PLUS:
        raise PlusPlanRequiredError

    period_start, period_end = _waste_watch_period(household.timezone, now)

    rows = _waste_watch_rows(
        db, household.id, period_start, period_end, limit=RANKING_LIMIT
    )
    catalog = _displayable_waste_products(db, rows)
    return [
        WasteWatchItemRead(
            product_barcode=row.product_barcode,
            product_name=product.name,
            brands=product.brands,
            product_quantity=product.quantity,
            image_url=product.image_url,
            discarded_event_count=int(row.discarded_event_count),
            discarded_quantity=int(row.discarded_quantity),
            last_discarded_at=row.last_discarded_at,
        )
        for row in rows
        if (product := catalog.get(row.product_barcode)) is not None
        and product.name is not None
        and product.name.strip()
    ]


def get_household_overview(
    db: Session,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> HouseholdOverviewRead:
    result = get_current_household(db, user_id)
    if result is None:
        raise HouseholdNotFoundError
    household, _membership = result
    if household.plan != HouseholdPlan.PLUS:
        raise PlusPlanRequiredError

    period_start, period_end = _insight_period(household.timezone, now)
    summary = _consumption_summary(
        _consumption_aggregates(db, household.id, period_start, period_end)
    )
    return HouseholdOverviewRead(
        period=ConsumptionInsightPeriod(
            days=INSIGHT_PERIOD_DAYS,
            start=period_start,
            end=period_end,
        ),
        used_quantity=summary.consumed_quantity,
        discarded_quantity=summary.discarded_quantity,
        waste_ratio=summary.waste_ratio,
        repeated_waste_product_count=count_repeated_waste_products(
            db,
            household.id,
            period_start,
            period_end,
        ),
        repurchase_candidate_count=count_shopping_suggestion_candidates(
            db, household.id
        ),
        expiry_attention_product_count=count_expiry_attention_items(
            db, household.id
        ),
    )
