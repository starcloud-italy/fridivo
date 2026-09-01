import enum
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class StorageLocation(str, enum.Enum):
    FRIDGE = "fridge"
    FREEZER = "freezer"
    PANTRY = "pantry"
    OTHER = "other"


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_items_quantity_positive"),
        UniqueConstraint(
            "household_id",
            "product_barcode",
            name="uq_inventory_items_household_product",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The external products table is deliberately not owned by application metadata.
    # Product existence is enforced by the inventory service before insertion.
    product_barcode: Mapped[str] = mapped_column(String(14), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    storage_location: Mapped[StorageLocation] = mapped_column(
        Enum(
            StorageLocation,
            name="storage_location",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    household = relationship("Household", back_populates="inventory_items")

