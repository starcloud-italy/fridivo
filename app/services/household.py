from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.household import Household, HouseholdMember


def get_current_household(db: Session, user_id: UUID) -> tuple[Household, HouseholdMember] | None:
    statement = (
        select(Household, HouseholdMember)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == user_id)
        .order_by(HouseholdMember.created_at, HouseholdMember.household_id)
        .limit(1)
    )
    return db.execute(statement).one_or_none()
