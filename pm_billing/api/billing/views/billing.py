"""Billing views — balance, transactions, Stripe checkout, webhook."""
import logging

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..conf import billing_settings
from ..models import CreditBalance, CreditTransaction
from ..serializers.billing import (
    CheckoutSessionCreateSerializer,
    CreditBalanceSerializer,
    CreditTransactionSerializer,
)
from ..services.stripe import create_checkout_session, handle_checkout_completed

logger = logging.getLogger(__name__)


class BalanceView(APIView):
    """GET current user's credit balance."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        balance_obj, _ = CreditBalance.objects.get_or_create(user=request.user)
        serializer = CreditBalanceSerializer(balance_obj)
        data = serializer.data
        data['stripe_enabled'] = bool(billing_settings.stripe_secret_key)
        return Response(data)


class TransactionListView(ListAPIView):
    """GET paginated transaction history for the current user."""

    permission_classes = [IsAuthenticated]
    serializer_class = CreditTransactionSerializer

    def get_queryset(self):
        return CreditTransaction.objects.filter(
            user=self.request.user
        ).order_by('-created_at')


class CheckoutView(APIView):
    """POST to create a Stripe Checkout session for purchasing credits."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not billing_settings.stripe_secret_key:
            return Response(
                {'error': 'Billing is temporarily unavailable.', 'billing_disabled': True},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = CheckoutSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data['amount']
        success_url = serializer.validated_data.get('success_url')
        cancel_url = serializer.validated_data.get('cancel_url')

        try:
            result = create_checkout_session(
                user=request.user,
                amount=amount,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Failed to create checkout session: {e}")
            return Response(
                {'error': 'Failed to create checkout session.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class StripeWebhookView(APIView):
    """POST endpoint for Stripe webhook events."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
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
