from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.consumption import ConsumptionEvent, ConsumptionEventType
from app.schemas.insights import (
    ConsumptionInsightPeriod,
    ConsumptionInsightsRead,
    ConsumptionInsightSummary,
    ProductConsumptionInsight,
)
from app.services.consumption import _household_id_for_user
from app.services.products import get_products_by_barcodes


INSIGHT_PERIOD_DAYS = 30
RANKING_LIMIT = 5
USED_EVENT_TYPES = (ConsumptionEventType.CONSUMED, ConsumptionEventType.FINISHED)


def _waste_ratio(consumed_quantity: int, discarded_quantity: int) -> float | None:
    total = consumed_quantity + discarded_quantity
    return discarded_quantity / total if total else None


def get_consumption_insights(
    db: Session,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> ConsumptionInsightsRead:
    household_id = _household_id_for_user(db, user_id)
    period_end = now or datetime.now(timezone.utc)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    period_start = period_end - timedelta(days=INSIGHT_PERIOD_DAYS)

    used_quantity = func.coalesce(
        func.sum(case((ConsumptionEvent.event_type.in_(USED_EVENT_TYPES), ConsumptionEvent.quantity), else_=0)),
        0,
    ).label("consumed_quantity")
    discarded_quantity = func.coalesce(
        func.sum(case((ConsumptionEvent.event_type == ConsumptionEventType.DISCARDED, ConsumptionEvent.quantity), else_=0)),
        0,
    ).label("discarded_quantity")

    aggregates = list(
        db.execute(
            select(
                ConsumptionEvent.product_barcode,
                used_quantity,
                discarded_quantity,
                func.count().filter(
                    ConsumptionEvent.event_type == ConsumptionEventType.CONSUMED
                ).label("consumed_event_count"),
                func.count().filter(
                    ConsumptionEvent.event_type == ConsumptionEventType.FINISHED
                ).label("finished_event_count"),
                func.count().filter(
                    ConsumptionEvent.event_type == ConsumptionEventType.DISCARDED
                ).label("discarded_event_count"),
            )
            .where(
                ConsumptionEvent.household_id == household_id,
                ConsumptionEvent.occurred_at >= period_start,
                ConsumptionEvent.occurred_at <= period_end,
            )
            .group_by(ConsumptionEvent.product_barcode)
        )
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
    total_consumed = sum(item.consumed_quantity for item in products)
    total_discarded = sum(item.discarded_quantity for item in products)
    summary = ConsumptionInsightSummary(
        consumed_quantity=total_consumed,
        discarded_quantity=total_discarded,
        consumed_event_count=sum(item.consumed_event_count for item in products),
        finished_event_count=sum(item.finished_event_count for item in products),
        discarded_event_count=sum(item.discarded_event_count for item in products),
        distinct_products=len(products),
        waste_ratio=_waste_ratio(total_consumed, total_discarded),
    )
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
