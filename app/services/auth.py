from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.household import Household, HouseholdMember, HouseholdPlan, HouseholdRole
from app.models.user import User
from app.schemas.auth import RegisterRequest


class EmailAlreadyExistsError(Exception):
    pass


def register_user(db: Session, data: RegisterRequest) -> tuple[User, str]:
    email = str(data.email).strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise EmailAlreadyExistsError

    user = User(
        email=email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        language_code=data.language_code,
        country_code=data.country_code,
    )
    personal_name = data.household_name or data.first_name or email.split("@", maxsplit=1)[0]
    household = Household(
        name=personal_name,
        country_code=data.country_code,
        default_language_code=data.language_code,
        currency_code=data.currency_code,
        timezone=data.timezone,
        plan=HouseholdPlan.FREE,
    )
    membership = HouseholdMember(user=user, household=household, role=HouseholdRole.OWNER)
    db.add_all((user, household, membership))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise EmailAlreadyExistsError from exc
    db.refresh(user)
    return user, create_access_token(user.id)


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user
