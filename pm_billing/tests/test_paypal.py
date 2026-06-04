"""PayPal provider coverage for pm-billing."""
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from pm_billing.api.billing.models import CreditBalance, CreditTransaction, PayPalCheckoutSession
from pm_billing.api.billing.providers.paypal import PayPalProvider
from pm_billing.api.billing.providers.base import PaymentProviderError
from pm_billing.api.billing.views.billing import PayPalWebhookView
from .utils import requires_pm_billing_app


PAYPAL_SETTINGS = {
    'PAYMENT_PROVIDER': 'paypal',
    'PAYPAL_CLIENT_ID': 'client-id',
    'PAYPAL_CLIENT_SECRET': 'client-secret',
    'PAYPAL_WEBHOOK_ID': 'webhook-id',
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
@requires_pm_billing_app
class PayPalProviderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='paypal',
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

    def test_create_checkout_paypal_api_error_is_user_safe(self):
        with patch('pm_billing.api.billing.providers.paypal.requests.post') as mock_post:
            mock_post.side_effect = [
                fake_response(data={'access_token': 'token'}),
                fake_response(status_code=422, text='{"name":"UNPROCESSABLE_ENTITY"}'),
            ]

            with self.assertRaises(PaymentProviderError) as ctx:
                PayPalProvider().create_checkout(
                    self.user,
                    Decimal('25.00'),
                    'http://localhost/success',
                    'http://localhost/cancel',
                )

        self.assertEqual(ctx.exception.code, 'paypal_create_order_failed')
        self.assertEqual(ctx.exception.provider, 'paypal')
        self.assertFalse(PayPalCheckoutSession.objects.exists())

    def test_create_checkout_requires_approval_url(self):
        with patch('pm_billing.api.billing.providers.paypal.requests.post') as mock_post:
            mock_post.side_effect = [
                fake_response(data={'access_token': 'token'}),
                fake_response(data={'id': 'ORDER-123', 'status': 'CREATED', 'links': []}),
            ]

            with self.assertRaises(PaymentProviderError) as ctx:
                PayPalProvider().create_checkout(
                    self.user,
                    Decimal('25.00'),
                    'http://localhost/success',
                    'http://localhost/cancel',
                )

        self.assertEqual(ctx.exception.code, 'paypal_missing_approval_url')

    def test_capture_rejects_mismatched_user_and_marks_session_failed(self):
        other_user = get_user_model().objects.create_user(
            username='other-paypal',
            email='other-paypal@example.com',
            password='password123',
        )
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
                'custom_id': str(other_user.id),
                'amount': {'currency_code': 'USD', 'value': '25.00'},
                'payments': {'captures': [{'id': 'CAPTURE-123', 'status': 'COMPLETED'}]},
            }],
        }
        with patch('pm_billing.api.billing.providers.paypal.requests.post') as mock_post:
            mock_post.side_effect = [
                fake_response(data={'access_token': 'token'}),
                fake_response(data=completed_order),
            ]

            with self.assertRaises(PaymentProviderError) as ctx:
                PayPalProvider().capture_checkout(self.user, 'ORDER-123')

        self.assertEqual(ctx.exception.code, 'paypal_order_not_creditable')
        self.assertEqual(PayPalCheckoutSession.objects.get(order_id='ORDER-123').status, 'failed')
        self.assertFalse(CreditTransaction.objects.filter(payment_provider='paypal').exists())

    def test_webhook_verifies_fetches_order_and_credits_user(self):
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
        request = APIRequestFactory().post(
            '/billing/webhook/paypal/',
            {
                'event_type': 'PAYMENT.CAPTURE.COMPLETED',
                'resource': {
                    'id': 'CAPTURE-123',
                    'status': 'COMPLETED',
                    'supplementary_data': {'related_ids': {'order_id': 'ORDER-123'}},
                },
            },
            format='json',
            HTTP_PAYPAL_AUTH_ALGO='SHA256withRSA',
            HTTP_PAYPAL_CERT_URL='https://api-m.sandbox.paypal.com/cert',
            HTTP_PAYPAL_TRANSMISSION_ID='transmission-id',
            HTTP_PAYPAL_TRANSMISSION_SIG='transmission-signature',
            HTTP_PAYPAL_TRANSMISSION_TIME='2026-06-04T13:18:00Z',
        )
        with patch('pm_billing.api.billing.providers.paypal.requests.post') as mock_post, \
             patch('pm_billing.api.billing.providers.paypal.requests.get') as mock_get:
            mock_post.side_effect = [
                fake_response(data={'access_token': 'token'}),
                fake_response(data={'verification_status': 'SUCCESS'}),
                fake_response(data={'access_token': 'token'}),
            ]
            mock_get.return_value = fake_response(data=completed_order)

            response = PayPalWebhookView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok'})
        self.assertEqual(CreditBalance.objects.get(user=self.user).balance, Decimal('25.000000'))
        self.assertEqual(PayPalCheckoutSession.objects.get(order_id='ORDER-123').status, 'credited')

    def test_webhook_rejects_missing_signature_headers(self):
        request = APIRequestFactory().post(
            '/billing/webhook/paypal/',
            {'event_type': 'PAYMENT.CAPTURE.COMPLETED', 'resource': {}},
            format='json',
        )

        response = PayPalWebhookView.as_view()(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'error': 'Invalid signature'})
