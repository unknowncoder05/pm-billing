"""Provider factory and adapter coverage."""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from pm_billing.api.billing.models import CreditTransaction
from pm_billing.api.billing.providers import get_payment_provider
from pm_billing.api.billing.providers.base import PaymentProviderError
from pm_billing.api.billing.providers.paypal import PayPalProvider
from pm_billing.api.billing.providers.stripe import StripeProvider
from pm_billing.api.billing.services.stripe import handle_checkout_completed
from .utils import requires_pm_billing_app


@requires_pm_billing_app
class ProviderFactoryTests(TestCase):
    @override_settings(PAYMENT_PROVIDER='paypal')
    def test_factory_returns_paypal_provider(self):
        self.assertIsInstance(get_payment_provider(), PayPalProvider)

    @override_settings(PAYMENT_PROVIDER='stripe')
    def test_factory_returns_stripe_provider(self):
        self.assertIsInstance(get_payment_provider(), StripeProvider)

    def test_provider_error_response_data_includes_provider(self):
        error = PaymentProviderError('Unavailable', code='provider_down', provider='paypal')

        self.assertEqual(error.as_response_data(), {
            'error': 'Unavailable',
            'code': 'provider_down',
            'payment_provider': 'paypal',
        })


@override_settings(STRIPE_SECRET_KEY='sk_test_package', STRIPE_WEBHOOK_SECRET='whsec_test')
@requires_pm_billing_app
class StripeProviderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='stripe',
            email='stripe@example.com',
            password='password123',
        )

    def test_stripe_provider_adds_provider_to_checkout_result(self):
        with patch(
            'pm_billing.api.billing.providers.stripe.create_checkout_session',
            return_value={'checkout_url': 'https://stripe.test/checkout', 'session_id': 'cs_test_123'},
        ) as mock_create:
            result = StripeProvider().create_checkout(
                self.user,
                Decimal('10.00'),
                'http://localhost/success',
                'http://localhost/cancel',
            )

        self.assertEqual(result, {
            'checkout_url': 'https://stripe.test/checkout',
            'session_id': 'cs_test_123',
            'provider': 'stripe',
        })
        mock_create.assert_called_once()

    def test_stripe_webhook_invalid_payload_returns_400(self):
        request = APIRequestFactory().post(
            '/billing/webhook/',
            data=b'not-json',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='bad-signature',
        )
        with patch('stripe.Webhook.construct_event', side_effect=ValueError):
            response = StripeProvider().handle_webhook(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'error': 'Invalid payload'})

    def test_handle_checkout_completed_is_idempotent(self):
        event_data = {
            'id': 'cs_test_123',
            'client_reference_id': str(self.user.id),
            'payment_intent': 'pi_test_123',
            'metadata': {'credit_amount': '10.00'},
        }

        first = handle_checkout_completed(event_data)
        second = handle_checkout_completed(event_data)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            CreditTransaction.objects.filter(stripe_checkout_session_id='cs_test_123').count(),
            1,
        )
