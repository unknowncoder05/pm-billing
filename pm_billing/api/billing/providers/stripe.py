"""Stripe payment provider adapter."""
import logging

from rest_framework import status
from rest_framework.response import Response

from ..conf import billing_settings
from ..services.stripe import create_checkout_session, handle_checkout_completed
from .base import PaymentProvider

logger = logging.getLogger(__name__)


class StripeProvider(PaymentProvider):
    """Hosted Stripe Checkout provider."""

    def is_configured(self) -> bool:
        return bool(billing_settings.stripe_secret_key)

    def create_checkout(self, user, amount, success_url: str, cancel_url: str) -> dict:
        result = create_checkout_session(
            user=user,
            amount=amount,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        result['provider'] = 'stripe'
        return result

    def handle_webhook(self, request) -> Response:
        try:
            import stripe  # noqa: PLC0415
        except ImportError:
            logger.error("stripe package not installed; webhook rejected")
            return Response({'error': 'Billing not available.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
        webhook_secret = billing_settings.stripe_webhook_secret

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except ValueError:
            logger.warning("Invalid Stripe webhook payload")
            return Response({'error': 'Invalid payload'}, status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError:
            logger.warning("Invalid Stripe webhook signature")
            return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

        if event['type'] == 'checkout.session.completed':
            handle_checkout_completed(event['data']['object'])

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)
