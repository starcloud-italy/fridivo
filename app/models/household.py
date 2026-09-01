import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class HouseholdRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class Household(Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    default_language_code: Mapped[str] = mapped_column(String(10), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    memberships = relationship(
        "HouseholdMember", back_populates="household", cascade="all, delete-orphan"
    )
    inventory_items = relationship(
        "InventoryItem", back_populates="household", cascade="all, delete-orphan"
    )


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "household_id", name="pk_household_members"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("households.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    role: Mapped[HouseholdRole] = mapped_column(
        Enum(HouseholdRole, name="household_role", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship("User", back_populates="memberships")
    household = relationship("Household", back_populates="memberships")
