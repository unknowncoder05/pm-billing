"""Billing views — balance, transactions, checkout, webhook."""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from ..models import CreditBalance, CreditTransaction
from ..providers import get_payment_provider
from ..providers.base import PaymentProviderError
from ..serializers.billing import (
    CheckoutSessionCreateSerializer,
    CreditBalanceSerializer,
    CreditTransactionSerializer,
)

logger = logging.getLogger(__name__)


class CheckoutRateThrottle(UserRateThrottle):
    """Limit checkout creation/capture attempts per user."""

    rate = '10/hour'
    scope = 'checkout'


class BalanceView(APIView):
    """GET current user's credit balance."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        balance_obj, _ = CreditBalance.objects.get_or_create(user=request.user)
        serializer = CreditBalanceSerializer(balance_obj)
        data = serializer.data
        data['payment_enabled'] = get_payment_provider().is_configured()
        data['payment_provider'] = getattr(settings, 'PAYMENT_PROVIDER', 'stripe')
        data['stripe_enabled'] = data['payment_enabled']
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
    """POST to create a checkout session/order with the active provider."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [CheckoutRateThrottle]

    def post(self, request):
        serializer = CheckoutSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = get_payment_provider()
        if not provider.is_configured():
            return Response(
                {
                    'error': 'Billing is temporarily unavailable.',
                    'billing_disabled': True,
                    'payment_provider': getattr(settings, 'PAYMENT_PROVIDER', 'stripe'),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        amount = serializer.validated_data['amount']
        success_url = serializer.validated_data.get('success_url', '')
        cancel_url = serializer.validated_data.get('cancel_url', '')

        try:
            result = provider.create_checkout(
                user=request.user,
                amount=amount,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return Response(result, status=status.HTTP_200_OK)
        except PaymentProviderError as e:
            logger.warning(
                "Payment provider failed to create checkout: provider=%s code=%s diagnostics=%s",
                e.provider,
                e.code,
                e.diagnostics,
            )
            return Response(e.as_response_data(), status=e.status_code)
        except Exception as e:
            logger.error(f"Failed to create checkout session: {e}")
            return Response(
                {'error': 'Failed to create checkout session.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CheckoutCaptureView(APIView):
    """POST to capture a provider checkout after hosted approval."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [CheckoutRateThrottle]

    def post(self, request):
        provider = get_payment_provider()
        capture_checkout = getattr(provider, 'capture_checkout', None)
        if not callable(capture_checkout):
            return Response(
                {'error': 'The active payment provider does not require checkout capture.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order_id = request.data.get('order_id') or request.data.get('session_id')
        try:
            result = capture_checkout(request.user, order_id)
            return Response(result, status=status.HTTP_200_OK)
        except PaymentProviderError as e:
            logger.warning(
                "Payment provider failed to capture checkout: provider=%s code=%s diagnostics=%s",
                e.provider,
                e.code,
                e.diagnostics,
            )
            return Response(e.as_response_data(), status=e.status_code)
        except Exception as e:
            logger.error(f"Failed to capture checkout: {e}")
            return Response(
                {'error': 'Failed to capture checkout.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class StripeWebhookView(APIView):
    """POST endpoint for Stripe webhook events."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from ..providers.stripe import StripeProvider
        return StripeProvider().handle_webhook(request)


class PayPalWebhookView(APIView):
    """POST endpoint for PayPal webhook events."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from ..providers.paypal import PayPalProvider
        return PayPalProvider().handle_webhook(request)
