"""Billing API view coverage."""
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from pm_billing.api.billing.models import CreditBalance
from pm_billing.api.billing.views.billing import CheckoutView
from .utils import requires_pm_billing_app


class FakeProvider:
    def __init__(self, configured=True, checkout_result=None, capture_result=None):
        self.configured = configured
        self.checkout_result = checkout_result or {
            'checkout_url': 'https://provider.test/checkout',
            'session_id': 'SESSION-123',
            'provider': 'fake',
        }
        self.capture_result = capture_result or {'status': 'ok', 'transaction_id': 123}

    def is_configured(self):
        return self.configured

    def create_checkout(self, **kwargs):
        self.checkout_kwargs = kwargs
        return self.checkout_result

    def capture_checkout(self, user, order_id):
        self.capture_user = user
        self.capture_order_id = order_id
        return self.capture_result


@override_settings(ROOT_URLCONF='pm_billing.api.billing.urls', PAYMENT_PROVIDER='paypal')
@requires_pm_billing_app
class BillingViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='views',
            email='views@example.com',
            password='password123',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_balance_returns_provider_flags(self):
        CreditBalance.objects.update_or_create(
            user=self.user,
            defaults={'balance': Decimal('12.34')},
        )
        with patch('pm_billing.api.billing.views.billing.get_payment_provider', return_value=FakeProvider(configured=True)):
            response = self.client.get('/billing/balance/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['payment_enabled'], True)
        self.assertEqual(response.data['payment_provider'], 'paypal')
        self.assertEqual(response.data['stripe_enabled'], True)
        self.assertEqual(response.data['balance'], '12.340000')

    def test_checkout_returns_503_when_provider_unconfigured(self):
        request = APIRequestFactory().post('/billing/checkout/', {'amount': '10.00'}, format='json')
        force_authenticate(request, user=self.user)
        with patch('pm_billing.api.billing.views.billing.get_payment_provider', return_value=FakeProvider(configured=False)):
            response = CheckoutView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['billing_disabled'], True)
        self.assertEqual(response.data['payment_provider'], 'paypal')

    def test_checkout_calls_active_provider(self):
        provider = FakeProvider()
        with patch('pm_billing.api.billing.views.billing.get_payment_provider', return_value=provider):
            response = self.client.post(
                '/billing/checkout/',
                {
                    'amount': '10.00',
                    'success_url': 'http://localhost/success',
                    'cancel_url': 'http://localhost/cancel',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['session_id'], 'SESSION-123')
        self.assertEqual(provider.checkout_kwargs['user'], self.user)
        self.assertEqual(provider.checkout_kwargs['amount'], Decimal('10.00'))

    def test_capture_returns_400_when_provider_has_no_capture(self):
        provider = Mock()
        provider.is_configured.return_value = True
        provider.capture_checkout = None
        with patch('pm_billing.api.billing.views.billing.get_payment_provider', return_value=provider):
            response = self.client.post('/billing/checkout/capture/', {'order_id': 'ORDER-123'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('does not require checkout capture', response.data['error'])

    def test_capture_calls_active_provider(self):
        provider = FakeProvider()
        with patch('pm_billing.api.billing.views.billing.get_payment_provider', return_value=provider):
            response = self.client.post('/billing/checkout/capture/', {'order_id': 'ORDER-123'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok', 'transaction_id': 123})
        self.assertEqual(provider.capture_user, self.user)
        self.assertEqual(provider.capture_order_id, 'ORDER-123')
