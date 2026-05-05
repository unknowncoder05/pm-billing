"""Stripe integration for credit purchases."""
import logging
from decimal import Decimal

from ..conf import billing_settings
from ..models import CreditTransaction
from .credits import add_credits

logger = logging.getLogger(__name__)


def create_checkout_session(user, amount, success_url=None, cancel_url=None):
    """Create a Stripe Checkout Session for purchasing credits."""
    try:
        import stripe  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("stripe package is not installed. Add it to requirements.")
    stripe.api_key = billing_settings.stripe_secret_key

    from django.conf import settings
    app_name = getattr(settings, 'APP_NAME', 'App')
    amount_cents = int(Decimal(str(amount)) * 100)

    if not success_url:
        success_url = billing_settings.stripe_success_url
    if not cancel_url:
        cancel_url = billing_settings.stripe_cancel_url

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': f'{app_name} Credits — ${amount}',
                    'description': f'Add ${amount} USD in credits to your account',
                },
                'unit_amount': amount_cents,
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user.id),
        metadata={
            'user_id': str(user.id),
            'credit_amount': str(amount),
        },
    )

    logger.info(
        f"Created Stripe checkout session {session.id} for user {user.id}, amount=${amount}"
    )

    return {
        'checkout_url': session.url,
        'session_id': session.id,
    }


def handle_checkout_completed(event_data):
    """Handle Stripe checkout.session.completed webhook event."""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    session = event_data
    session_id = session.get('id', '')
    metadata = session.get('metadata', {})
    user_id = metadata.get('user_id') or session.get('client_reference_id')
    credit_amount = metadata.get('credit_amount')
    payment_intent_id = session.get('payment_intent', '')

    if not user_id or not credit_amount:
        logger.error(f"Missing user_id or credit_amount in checkout session {session_id}")
        return None

    if CreditTransaction.objects.filter(stripe_checkout_session_id=session_id).exists():
        logger.info(f"Checkout session {session_id} already processed, skipping")
        return None

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for checkout session {session_id}")
        return None

    amount = Decimal(credit_amount)

    txn = add_credits(
        user=user,
        amount=amount,
        transaction_type='purchase',
        description=f'Stripe purchase — ${amount:.2f}',
        stripe_payment_intent_id=payment_intent_id,
        stripe_checkout_session_id=session_id,
    )

    logger.info(f"Processed checkout {session_id}: added ${amount:.2f} to user {user_id}")
    return txn
