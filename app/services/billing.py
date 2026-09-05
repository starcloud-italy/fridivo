from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import stripe
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import StripeWebhookEvent
from app.models.household import Household, HouseholdPlan
from app.models.user import User


class BillingConfigurationError(Exception):
    pass


class BillingProviderError(Exception):
    pass


class BillingEventError(Exception):
    pass


class BillingAssociationError(Exception):
    pass


class StaleBillingEvent(Exception):
    pass


@dataclass(frozen=True)
class CheckoutReturnUrls:
    success: str
    cancel: str


def _stripe_client(secret_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(secret_key)


def _secret_value(secret) -> str:
    return secret.get_secret_value().strip() if secret is not None else ""


def create_plus_checkout_session(
    household: Household,
    user: User,
    return_urls: CheckoutReturnUrls,
) -> str:
    secret_key = _secret_value(settings.stripe_secret_key)
    price_id = (settings.stripe_plus_monthly_price_id or "").strip()
    if not secret_key or not price_id:
        raise BillingConfigurationError

    household_id = str(household.id)
    try:
        checkout_params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": return_urls.success,
            "cancel_url": return_urls.cancel,
            "client_reference_id": household_id,
            "metadata": {"household_id": household_id},
            "subscription_data": {"metadata": {"household_id": household_id}},
        }
        if household.stripe_customer_id:
            checkout_params["customer"] = household.stripe_customer_id
        else:
            checkout_params["customer_email"] = user.email
        session = _stripe_client(secret_key).v1.checkout.sessions.create(checkout_params)
    except stripe.StripeError:
        raise BillingProviderError from None

    checkout_url = getattr(session, "url", None)
    if not checkout_url:
        raise BillingProviderError
    return str(checkout_url)


ENTITLED_STATUSES = frozenset({"active", "trialing"})
NON_ENTITLED_STATUSES = frozenset(
    {"canceled", "unpaid", "incomplete", "incomplete_expired", "paused"}
)
SUPPORTED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }
)


def plan_for_subscription_status(
    subscription_status: str, current_plan: HouseholdPlan
) -> HouseholdPlan:
    if subscription_status in ENTITLED_STATUSES:
        return HouseholdPlan.PLUS
    if subscription_status in NON_ENTITLED_STATUSES:
        return HouseholdPlan.FREE
    # past_due and future Stripe statuses preserve the existing entitlement.
    return current_plan


def construct_stripe_event(payload: bytes, signature: str | None):
    webhook_secret = _secret_value(settings.stripe_webhook_secret)
    if not webhook_secret:
        raise BillingConfigurationError
    if not signature:
        raise BillingEventError
    try:
        return stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise BillingEventError from None


def _value(value, key: str, default=None):
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _stripe_id(value) -> str | None:
    if isinstance(value, str):
        return value
    identifier = _value(value, "id") if value is not None else None
    return str(identifier) if identifier else None


def _subscription_period_end(subscription) -> datetime | None:
    timestamp = _value(subscription, "current_period_end")
    if timestamp is None:
        items = _value(_value(subscription, "items", {}), "data", []) or []
        timestamps = [
            _value(item, "current_period_end")
            for item in items
            if _value(item, "current_period_end") is not None
        ]
        timestamp = max(timestamps) if timestamps else None
    if timestamp is None:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


def _subscription_id_from_invoice(invoice) -> str | None:
    legacy_subscription = _stripe_id(_value(invoice, "subscription"))
    if legacy_subscription:
        return legacy_subscription
    parent = _value(invoice, "parent", {})
    subscription_details = _value(parent, "subscription_details", {})
    return _stripe_id(_value(subscription_details, "subscription"))


def _retrieve_subscription(subscription_id: str):
    secret_key = _secret_value(settings.stripe_secret_key)
    if not secret_key:
        raise BillingConfigurationError
    try:
        return _stripe_client(secret_key).v1.subscriptions.retrieve(subscription_id)
    except stripe.StripeError:
        raise BillingProviderError from None


def _household_by_reference(db: Session, reference: str | None) -> Household:
    try:
        household_id = UUID(str(reference))
    except (TypeError, ValueError):
        raise BillingAssociationError from None
    household = db.scalar(
        select(Household).where(Household.id == household_id).with_for_update()
    )
    if household is None:
        raise BillingAssociationError
    return household


def _assert_identifiers_available(
    db: Session, household: Household, customer_id: str, subscription_id: str
) -> None:
    conflict = db.scalar(
        select(Household.id).where(
            Household.id != household.id,
            or_(
                Household.stripe_customer_id == customer_id,
                Household.stripe_subscription_id == subscription_id,
            ),
        )
    )
    if conflict is not None:
        raise BillingAssociationError


def _link_checkout_household(
    db: Session, checkout_session, customer_id: str, subscription_id: str
) -> Household:
    metadata = _value(checkout_session, "metadata", {}) or {}
    metadata_reference = _value(metadata, "household_id")
    client_reference = _value(checkout_session, "client_reference_id")
    if (
        metadata_reference
        and client_reference
        and str(metadata_reference) != str(client_reference)
    ):
        raise BillingAssociationError
    household = _household_by_reference(db, metadata_reference or client_reference)
    _assert_identifiers_available(db, household, customer_id, subscription_id)
    if household.stripe_customer_id not in (None, customer_id):
        raise BillingAssociationError
    if household.stripe_subscription_id not in (None, subscription_id):
        replaceable = (
            household.plan == HouseholdPlan.FREE
            and household.subscription_status not in ENTITLED_STATUSES | {"past_due"}
        )
        if not replaceable:
            raise BillingAssociationError
    household.stripe_customer_id = customer_id
    household.stripe_subscription_id = subscription_id
    return household


def _household_for_subscription(db: Session, subscription) -> Household:
    subscription_id = _stripe_id(subscription)
    customer_id = _stripe_id(_value(subscription, "customer"))
    if not subscription_id or not customer_id:
        raise BillingEventError
    household = db.scalar(
        select(Household)
        .where(Household.stripe_subscription_id == subscription_id)
        .with_for_update()
    )
    if household is None:
        metadata = _value(subscription, "metadata", {}) or {}
        reference = _value(metadata, "household_id")
        if reference:
            household = _household_by_reference(db, reference)
        else:
            household = db.scalar(
                select(Household)
                .where(Household.stripe_customer_id == customer_id)
                .with_for_update()
            )
    if household is None:
        raise BillingAssociationError
    _assert_identifiers_available(db, household, customer_id, subscription_id)
    if household.stripe_customer_id not in (None, customer_id):
        raise BillingAssociationError
    if household.stripe_subscription_id not in (None, subscription_id):
        # The event belongs to an older subscription for the same Customer.
        # A verified stale event must not overwrite the Household's newer link.
        raise StaleBillingEvent
    household.stripe_customer_id = customer_id
    household.stripe_subscription_id = subscription_id
    return household


def _apply_subscription(household: Household, subscription) -> None:
    subscription_status = str(_value(subscription, "status") or "")
    if not subscription_status:
        raise BillingEventError
    household.subscription_status = subscription_status
    household.subscription_current_period_end = _subscription_period_end(subscription)
    household.subscription_cancel_at_period_end = bool(
        _value(subscription, "cancel_at_period_end", False)
    )
    household.plan = plan_for_subscription_status(subscription_status, household.plan)


def _reserve_event(db: Session, event_id: str, event_type: str) -> bool:
    statement = (
        postgresql_insert(StripeWebhookEvent)
        .values(event_id=event_id, event_type=event_type)
        .on_conflict_do_nothing(index_elements=[StripeWebhookEvent.event_id])
        .returning(StripeWebhookEvent.event_id)
    )
    return db.scalar(statement) is not None


def process_stripe_event(db: Session, event) -> bool:
    event_id = str(_value(event, "id") or "")
    event_type = str(_value(event, "type") or "")
    if not event_id or not event_type:
        raise BillingEventError
    if not _reserve_event(db, event_id, event_type):
        db.rollback()
        return False

    try:
        if event_type not in SUPPORTED_EVENT_TYPES:
            db.commit()
            return True
        event_object = _value(_value(event, "data", {}), "object")
        if event_object is None:
            raise BillingEventError

        if event_type == "checkout.session.completed":
            if _value(event_object, "mode") != "subscription":
                raise BillingEventError
            customer_id = _stripe_id(_value(event_object, "customer"))
            subscription_id = _stripe_id(_value(event_object, "subscription"))
            if not customer_id or not subscription_id:
                raise BillingEventError
            household = _link_checkout_household(
                db, event_object, customer_id, subscription_id
            )
            subscription = _retrieve_subscription(subscription_id)
            linked_household = _household_for_subscription(db, subscription)
            if linked_household.id != household.id:
                raise BillingAssociationError
            _apply_subscription(household, subscription)
        elif event_type.startswith("customer.subscription."):
            if event_type == "customer.subscription.deleted":
                subscription = event_object
            else:
                subscription_id = _stripe_id(event_object)
                if not subscription_id:
                    raise BillingEventError
                subscription = _retrieve_subscription(subscription_id)
            household = _household_for_subscription(db, subscription)
            _apply_subscription(household, subscription)
        else:
            subscription_id = _subscription_id_from_invoice(event_object)
            if not subscription_id:
                raise BillingAssociationError
            subscription = _retrieve_subscription(subscription_id)
            household = _household_for_subscription(db, subscription)
            _apply_subscription(household, subscription)
        db.commit()
        return True
    except StaleBillingEvent:
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
