import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ConsumptionEventType(str, enum.Enum):
    CONSUMED = "CONSUMED"
    FINISHED = "FINISHED"
    DISCARDED = "DISCARDED"


class ConsumptionEvent(Base):
    __tablename__ = "consumption_events"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_consumption_events_quantity_positive"),
        Index("ix_consumption_events_household_occurred_at", "household_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_barcode: Mapped[str] = mapped_column(String(14), nullable=False)
    event_type: Mapped[ConsumptionEventType] = mapped_column(
        Enum(
            ConsumptionEventType,
            name="consumption_event_type",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    household = relationship("Household", back_populates="consumption_events")
