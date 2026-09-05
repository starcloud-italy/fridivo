from dataclasses import dataclass

import stripe

from app.core.config import settings
from app.models.household import Household
from app.models.user import User


class BillingConfigurationError(Exception):
    pass


class BillingProviderError(Exception):
    pass


@dataclass(frozen=True)
class CheckoutReturnUrls:
    success: str
    cancel: str


def _stripe_client(secret_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(secret_key)


def create_plus_checkout_session(
    household: Household,
    user: User,
    return_urls: CheckoutReturnUrls,
) -> str:
    secret_key = (
        settings.stripe_secret_key.get_secret_value().strip()
        if settings.stripe_secret_key is not None
        else ""
    )
    price_id = (settings.stripe_plus_monthly_price_id or "").strip()
    if not secret_key or not price_id:
        raise BillingConfigurationError

    household_id = str(household.id)
    try:
        session = _stripe_client(secret_key).v1.checkout.sessions.create(
            {
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": return_urls.success,
                "cancel_url": return_urls.cancel,
                "customer_email": user.email,
                "client_reference_id": household_id,
                "metadata": {"household_id": household_id},
            }
        )
    except stripe.StripeError:
        raise BillingProviderError from None

    checkout_url = getattr(session, "url", None)
    if not checkout_url:
        raise BillingProviderError
    return str(checkout_url)
