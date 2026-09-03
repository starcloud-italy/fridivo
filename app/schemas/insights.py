from datetime import datetime

from pydantic import BaseModel

from app.models.consumption import ConsumptionEventType


class ConsumptionInsightPeriod(BaseModel):
    days: int
    start: datetime
    end: datetime


class ConsumptionInsightSummary(BaseModel):
    consumed_quantity: int
    discarded_quantity: int
    consumed_event_count: int
    finished_event_count: int
    discarded_event_count: int
    distinct_products: int
    waste_ratio: float | None


class ProductConsumptionInsight(BaseModel):
    barcode: str
    product_name: str | None
    brands: str | None
    image_url: str | None
    consumed_quantity: int
    discarded_quantity: int
    consumed_event_count: int
    finished_event_count: int
    discarded_event_count: int
    last_event: ConsumptionEventType
    last_event_at: datetime
    waste_ratio: float | None


class ConsumptionInsightsRead(BaseModel):
    period: ConsumptionInsightPeriod
    summary: ConsumptionInsightSummary
    most_consumed: list[ProductConsumptionInsight]
    most_discarded: list[ProductConsumptionInsight]
    products: list[ProductConsumptionInsight]
