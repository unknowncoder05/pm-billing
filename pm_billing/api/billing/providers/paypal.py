"""PayPal payment provider using Orders API v2."""
import logging
import uuid
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response

from ..models import CreditBalance, CreditTransaction, PayPalCheckoutSession
from .base import PaymentProvider, PaymentProviderError

logger = logging.getLogger(__name__)


class PayPalProvider(PaymentProvider):
    """Hosted PayPal checkout backed by server-side order capture."""

    def is_configured(self) -> bool:
        return bool(
            getattr(settings, 'PAYPAL_CLIENT_ID', '')
            and getattr(settings, 'PAYPAL_CLIENT_SECRET', '')
        )

    @property
    def base_url(self) -> str:
        environment = getattr(settings, 'PAYPAL_ENVIRONMENT', 'live')
        if environment == 'sandbox':
            return 'https://api-m.sandbox.paypal.com'
        return 'https://api-m.paypal.com'

    def _access_token(self) -> str:
        try:
            response = requests.post(
                f'{self.base_url}/v1/oauth2/token',
                auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                data={'grant_type': 'client_credentials'},
                headers={'Accept': 'application/json'},
                timeout=10,
            )
        except requests.RequestException as e:
            raise self._network_error('paypal_auth_network_error', e) from e
        if response.status_code >= 400:
            raise self._api_error(
                response,
                'paypal_auth_failed',
                'PayPal authentication failed. Please check the configured PayPal credentials.',
                status_code=503,
            )
        access_token = response.json().get('access_token')
        if not access_token:
            logger.error("PayPal authentication response missing access_token")
            raise PaymentProviderError(
                'PayPal authentication failed. Please check the configured PayPal credentials.',
                code='paypal_auth_malformed_response',
                provider='paypal',
                status_code=503,
            )
        return access_token

    def _headers(self, *, request_id=None):
        headers = {
            'Authorization': f'Bearer {self._access_token()}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if request_id:
            headers['PayPal-Request-Id'] = request_id
        return headers

    def create_checkout(self, user, amount, success_url: str, cancel_url: str) -> dict:
        amount = Decimal(str(amount)).quantize(Decimal('0.01'))
        if not success_url:
            success_url = getattr(settings, 'PAYPAL_SUCCESS_URL', '')
        if not cancel_url:
            cancel_url = getattr(settings, 'PAYPAL_CANCEL_URL', '')

        payload = {
            'intent': 'CAPTURE',
            'purchase_units': [{
                'reference_id': f'credits-{uuid.uuid4()}',
                'custom_id': str(user.id),
                'description': f'{getattr(settings, "APP_NAME", "App")} credits - ${amount}',
                'amount': {
                    'currency_code': 'USD',
                    'value': f'{amount:.2f}',
                },
            }],
            'payment_source': {
                'paypal': {
                    'experience_context': {
                        'payment_method_preference': 'IMMEDIATE_PAYMENT_REQUIRED',
                        'brand_name': getattr(settings, 'APP_NAME', 'App'),
                        'landing_page': 'LOGIN',
                        'user_action': 'PAY_NOW',
                        'return_url': success_url,
                        'cancel_url': cancel_url,
                    },
                },
            },
        }

        try:
            response = requests.post(
                f'{self.base_url}/v2/checkout/orders',
                json=payload,
                headers=self._headers(request_id=f'pm-order-{user.id}-{uuid.uuid4()}'),
                timeout=10,
            )
        except requests.RequestException as e:
            raise self._network_error('paypal_create_order_network_error', e) from e
        if response.status_code >= 400:
            raise self._api_error(
                response,
                'paypal_create_order_failed',
                'PayPal could not start checkout. Please try again in a few minutes.',
            )
        data = response.json()
        approve_url = next(
            (link.get('href') for link in data.get('links', []) if link.get('rel') == 'payer-action'),
            None,
        ) or next(
            (link.get('href') for link in data.get('links', []) if link.get('rel') == 'approve'),
            None,
        )
        if not approve_url:
            raise PaymentProviderError(
                'PayPal did not return a checkout approval link. Please try again.',
                code='paypal_missing_approval_url',
                provider='paypal',
                diagnostics={'order_id': data.get('id'), 'link_rels': [link.get('rel') for link in data.get('links', [])]},
            )

        order_id = data['id']
        PayPalCheckoutSession.objects.update_or_create(
            order_id=order_id,
            defaults={
                'user': user,
                'amount': amount,
                'currency': 'USD',
                'status': 'created',
                'last_error': '',
                'diagnostics': {
                    'create_status': data.get('status', ''),
                    'link_rels': [link.get('rel') for link in data.get('links', [])],
                },
            },
        )
        return {
            'checkout_url': approve_url,
            'session_id': order_id,
            'provider': 'paypal',
        }

    def capture_checkout(self, user, order_id: str) -> dict:
        if not order_id:
            raise ValueError('PayPal order id is required')

        try:
            response = requests.post(
                f'{self.base_url}/v2/checkout/orders/{order_id}/capture',
                headers=self._headers(request_id=f'pm-capture-{order_id}'),
                timeout=10,
            )
        except requests.RequestException as e:
            raise self._network_error('paypal_capture_network_error', e, order_id=order_id) from e
        if response.status_code >= 400:
            self._mark_session_failed(order_id, 'PayPal capture API failed', {'status_code': response.status_code})
            raise self._api_error(
                response,
                'paypal_capture_failed',
                'PayPal could not complete this payment. Please confirm the payment was approved and try again.',
                order_id=order_id,
            )
        order = response.json()
        txn = self._credit_completed_order(order, expected_user_id=str(user.id), order_id=order_id)
        if not txn:
            self._mark_session_failed(order_id, 'PayPal order was not eligible for crediting', order)
            raise PaymentProviderError(
                'PayPal payment was not completed or could not be verified. Please try checkout again.',
                code='paypal_order_not_creditable',
                provider='paypal',
                status_code=400,
                diagnostics={'order_id': order_id, **self._order_diagnostics(order)},
            )
        return {'status': 'ok', 'transaction_id': txn.id}

    def handle_webhook(self, request) -> Response:
        webhook_id = getattr(settings, 'PAYPAL_WEBHOOK_ID', '')
        if not webhook_id:
            logger.error("PAYPAL_WEBHOOK_ID not configured")
            return Response({'error': 'Webhook not configured'}, status=status.HTTP_400_BAD_REQUEST)

        payload = request.data
        if not isinstance(payload, dict):
            return Response({'error': 'Invalid payload'}, status=status.HTTP_400_BAD_REQUEST)

        if not self._verify_webhook(request, payload, webhook_id):
            return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

        event_type = payload.get('event_type', '')
        if event_type in {'PAYMENT.CAPTURE.COMPLETED', 'CHECKOUT.ORDER.COMPLETED'}:
            self._handle_payment_event(payload)

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

    def _verify_webhook(self, request, payload: dict, webhook_id: str) -> bool:
        headers = request.META
        verification_payload = {
            'auth_algo': headers.get('HTTP_PAYPAL_AUTH_ALGO', ''),
            'cert_url': headers.get('HTTP_PAYPAL_CERT_URL', ''),
            'transmission_id': headers.get('HTTP_PAYPAL_TRANSMISSION_ID', ''),
            'transmission_sig': headers.get('HTTP_PAYPAL_TRANSMISSION_SIG', ''),
            'transmission_time': headers.get('HTTP_PAYPAL_TRANSMISSION_TIME', ''),
            'webhook_id': webhook_id,
            'webhook_event': payload,
        }
        if not all(verification_payload[key] for key in (
            'auth_algo',
            'cert_url',
            'transmission_id',
            'transmission_sig',
            'transmission_time',
        )):
            return False

        try:
            response = requests.post(
                f'{self.base_url}/v1/notifications/verify-webhook-signature',
                json=verification_payload,
                headers=self._headers(),
                timeout=10,
            )
        except PaymentProviderError as e:
            logger.error("PayPal webhook verification auth failure: code=%s diagnostics=%s", e.code, e.diagnostics)
            return False
        except requests.RequestException as e:
            logger.error("PayPal webhook verification network failure: %s", e)
            return False
        if response.status_code >= 400:
            logger.error(
                "PayPal webhook verification API failed: status=%s body=%s",
                response.status_code,
                response.text[:1000],
            )
            return False
        return response.json().get('verification_status') == 'SUCCESS'

    def _handle_payment_event(self, payload: dict):
        resource = payload.get('resource') or {}
        order_id = self._order_id_from_resource(resource)
        if not order_id:
            logger.error("PayPal webhook missing related order id")
            return None

        try:
            response = requests.get(
                f'{self.base_url}/v2/checkout/orders/{order_id}',
                headers=self._headers(),
                timeout=10,
            )
        except requests.RequestException as e:
            logger.error("PayPal order fetch failed after webhook: order_id=%s error=%s", order_id, e)
            self._mark_session_failed(order_id, 'PayPal order fetch failed after webhook', {'error': str(e)})
            return None
        if response.status_code >= 400:
            logger.error(
                "PayPal order fetch failed after webhook: order_id=%s status=%s body=%s",
                order_id,
                response.status_code,
                response.text[:1000],
            )
            self._mark_session_failed(order_id, 'PayPal order fetch failed after webhook', {'status_code': response.status_code})
            return None
        return self._credit_completed_order(response.json(), order_id=order_id)

    def _credit_completed_order(self, order: dict, *, expected_user_id=None, order_id=None):
        session = None
        if order.get('status') != 'COMPLETED':
            logger.warning("PayPal order %s not completed (status=%s)", order.get('id'), order.get('status'))
            return None

        order_id = order_id or order.get('id', '')
        if order_id:
            session = PayPalCheckoutSession.objects.filter(order_id=order_id).select_related('user').first()

        purchase_units = order.get('purchase_units') or []
        if not purchase_units:
            logger.error("PayPal order %s missing purchase units", order_id)
            return None

        purchase_unit = purchase_units[0]
        paypal_user_id = purchase_unit.get('custom_id')
        stored_user_id = str(session.user_id) if session else None
        user_id = paypal_user_id or stored_user_id
        if expected_user_id and user_id != expected_user_id:
            logger.error(
                "PayPal order %s user mismatch: expected=%s paypal_custom_id=%s stored_user_id=%s diagnostics=%s",
                order_id,
                expected_user_id,
                paypal_user_id,
                stored_user_id,
                self._order_diagnostics(order),
            )
            return None
        if paypal_user_id and stored_user_id and paypal_user_id != stored_user_id:
            logger.error(
                "PayPal order %s custom_id mismatch: paypal_custom_id=%s stored_user_id=%s",
                order_id,
                paypal_user_id,
                stored_user_id,
            )
            return None
        if not user_id:
            logger.error("PayPal order %s missing user attribution diagnostics=%s", order_id, self._order_diagnostics(order))
            return None

        amount_info = purchase_unit.get('amount') or {}
        currency_code = amount_info.get('currency_code') or (session.currency if session else '')
        if currency_code != 'USD':
            logger.error(
                "PayPal order %s currency mismatch: paypal=%s stored=%s diagnostics=%s",
                order_id,
                amount_info.get('currency_code'),
                session.currency if session else None,
                self._order_diagnostics(order),
            )
            return None

        if amount_info.get('value') is not None:
            amount = Decimal(str(amount_info.get('value')))
        elif session:
            amount = session.amount
        else:
            logger.error("PayPal order %s missing amount and no stored session diagnostics=%s", order_id, self._order_diagnostics(order))
            return None

        if session and amount_info.get('value') is not None and amount != session.amount:
            logger.error(
                "PayPal order %s amount mismatch: paypal=%s stored=%s diagnostics=%s",
                order_id,
                amount,
                session.amount,
                self._order_diagnostics(order),
            )
            return None
        captures = (
            purchase_unit.get('payments', {})
            .get('captures', [])
        )
        if not captures or not any(capture.get('status') == 'COMPLETED' for capture in captures):
            logger.error("PayPal order %s has no completed capture", order_id)
            return None

        try:
            user = get_user_model().objects.get(id=user_id)
        except get_user_model().DoesNotExist:
            logger.error("User %s not found for PayPal order %s", user_id, order_id)
            return None

        try:
            with transaction.atomic():
                balance_obj, _ = CreditBalance.objects.select_for_update().get_or_create(user=user)
                existing = CreditTransaction.objects.filter(
                    payment_provider='paypal',
                    external_order_id=order_id,
                ).first()
                if existing:
                    logger.info("PayPal order %s already processed", order_id)
                    return existing

                balance_obj.balance += amount
                balance_obj.total_deposited += amount
                balance_obj.save(update_fields=['balance', 'total_deposited', 'updated_at'])
                txn = CreditTransaction.objects.create(
                    user=user,
                    amount=amount,
                    balance_after=balance_obj.balance,
                    transaction_type='purchase',
                    description=f'PayPal purchase - ${amount:.2f}',
                    payment_provider='paypal',
                    external_order_id=order_id,
                )
                if session:
                    session.status = 'credited'
                    session.last_error = ''
                    session.diagnostics = self._order_diagnostics(order)
                    session.save(update_fields=['status', 'last_error', 'diagnostics', 'updated_at'])
        except IntegrityError:
            logger.info("PayPal order %s already processed (race)", order_id)
            return CreditTransaction.objects.filter(
                payment_provider='paypal',
                external_order_id=order_id,
            ).first()

        logger.info("PayPal: credited $%0.2f to user %s", amount, user_id)
        return txn

    def _mark_session_failed(self, order_id: str, message: str, order: dict):
        if not order_id:
            return
        PayPalCheckoutSession.objects.filter(order_id=order_id).update(
            status='failed',
            last_error=message,
            diagnostics=self._order_diagnostics(order),
        )

    def _order_diagnostics(self, order: dict) -> dict:
        purchase_units = order.get('purchase_units') or []
        purchase_unit = purchase_units[0] if purchase_units else {}
        captures = (
            purchase_unit.get('payments', {})
            .get('captures', [])
        )
        amount = purchase_unit.get('amount') or {}
        return {
            'order_id': order.get('id', ''),
            'order_status': order.get('status', ''),
            'purchase_unit_count': len(purchase_units),
            'has_custom_id': bool(purchase_unit.get('custom_id')),
            'reference_id': purchase_unit.get('reference_id', ''),
            'amount_value': amount.get('value', ''),
            'currency_code': amount.get('currency_code', ''),
            'capture_count': len(captures),
            'capture_statuses': [capture.get('status', '') for capture in captures],
            'capture_ids': [capture.get('id', '') for capture in captures],
        }

    def _order_id_from_resource(self, resource: dict) -> str:
        order_id = resource.get('id') if resource.get('status') == 'COMPLETED' else ''
        related_ids = (
            resource.get('supplementary_data', {})
            .get('related_ids', {})
        )
        return related_ids.get('order_id') or order_id

    def _api_error(self, response, code, public_message, *, status_code=502, order_id=None):
        body = response.text[:1000]
        paypal_debug_id = response.headers.get('PayPal-Debug-Id', '') or response.headers.get('paypal-debug-id', '')
        diagnostics = {
            'http_status': response.status_code,
            'paypal_debug_id': paypal_debug_id,
            'order_id': order_id or '',
            'body': body,
        }
        logger.error(
            "PayPal API error: code=%s status=%s debug_id=%s order_id=%s body=%s",
            code,
            response.status_code,
            paypal_debug_id,
            order_id or '',
            body,
        )
        return PaymentProviderError(
            public_message,
            code=code,
            provider='paypal',
            status_code=status_code,
            diagnostics=diagnostics,
        )

    def _network_error(self, code, error, *, order_id=None):
        logger.error("PayPal network error: code=%s order_id=%s error=%s", code, order_id or '', error)
        return PaymentProviderError(
            'PayPal is temporarily unreachable. Please try again in a few minutes.',
            code=code,
            provider='paypal',
            status_code=503,
            diagnostics={'order_id': order_id or '', 'error': str(error)},
        )
