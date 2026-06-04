"""PayPal provider coverage for pm-billing."""
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from unittest import skipUnless

from pm_billing.api.billing.models import CreditBalance, CreditTransaction, PayPalCheckoutSession
from pm_billing.api.billing.providers.paypal import PayPalProvider


PAYPAL_SETTINGS = {
    'PAYMENT_PROVIDER': 'paypal',
    'PAYPAL_CLIENT_ID': 'client-id',
    'PAYPAL_CLIENT_SECRET': 'client-secret',
    'PAYPAL_ENVIRONMENT': 'sandbox',
    'PAYPAL_SUCCESS_URL': 'http://localhost:3000/billing/success',
    'PAYPAL_CANCEL_URL': 'http://localhost:3000/billing/cancel',
}


def fake_response(status_code=200, data=None, text='{}'):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = data or {}
    response.text = text
    response.headers = {'PayPal-Debug-Id': 'debug-123'}
    return response


@override_settings(**PAYPAL_SETTINGS)
@skipUnless('pm_billing' in settings.INSTALLED_APPS, 'pm_billing app is not installed in this Django settings module')
class PayPalProviderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email='paypal@example.com',
            password='password123',
        )

    def test_create_checkout_creates_paypal_order_session(self):
        with patch('pm_billing.api.billing.providers.paypal.requests.post') as mock_post:
            mock_post.side_effect = [
                fake_response(data={'access_token': 'token'}),
                fake_response(data={
                    'id': 'ORDER-123',
                    'status': 'CREATED',
                    'links': [{'rel': 'payer-action', 'href': 'https://paypal.test/checkout'}],
                }),
            ]

            result = PayPalProvider().create_checkout(
                self.user,
                Decimal('25.00'),
                'http://localhost/success',
                'http://localhost/cancel',
            )

        self.assertEqual(result['provider'], 'paypal')
        self.assertEqual(result['session_id'], 'ORDER-123')
        self.assertEqual(result['checkout_url'], 'https://paypal.test/checkout')

        session = PayPalCheckoutSession.objects.get(order_id='ORDER-123')
        self.assertEqual(session.user, self.user)
        self.assertEqual(session.amount, Decimal('25.00'))
        self.assertEqual(session.status, 'created')

    def test_capture_completed_order_adds_credits_once(self):
        PayPalCheckoutSession.objects.create(
            user=self.user,
            order_id='ORDER-123',
            amount=Decimal('25.00'),
            currency='USD',
        )
        completed_order = {
            'id': 'ORDER-123',
            'status': 'COMPLETED',
            'purchase_units': [{
                'custom_id': str(self.user.id),
                'amount': {'currency_code': 'USD', 'value': '25.00'},
                'payments': {'captures': [{'id': 'CAPTURE-123', 'status': 'COMPLETED'}]},
            }],
        }
        with patch('pm_billing.api.billing.providers.paypal.requests.post') as mock_post:
            mock_post.side_effect = [
                fake_response(data={'access_token': 'token'}),
                fake_response(data=completed_order),
            ]

            result = PayPalProvider().capture_checkout(self.user, 'ORDER-123')

        self.assertEqual(result['status'], 'ok')
        balance = CreditBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, Decimal('25.000000'))
        txn = CreditTransaction.objects.get(payment_provider='paypal', external_order_id='ORDER-123')
        self.assertEqual(txn.amount, Decimal('25.000000'))
        self.assertEqual(PayPalCheckoutSession.objects.get(order_id='ORDER-123').status, 'credited')

        duplicate = PayPalProvider()._credit_completed_order(completed_order, order_id='ORDER-123')
        self.assertEqual(duplicate.id, txn.id)
        self.assertEqual(CreditTransaction.objects.filter(payment_provider='paypal', external_order_id='ORDER-123').count(), 1)
