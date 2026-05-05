from django.conf import settings
from django.test.signals import setting_changed
from django.utils.translation import gettext_lazy as _


class BillingSettings:
    """
    Settings for PM Billing
    """

    def __init__(self):
        self._stripe_secret_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
        self._stripe_webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
        self._stripe_success_url = getattr(settings, 'STRIPE_SUCCESS_URL', 'http://localhost:3000/billing/success')
        self._stripe_cancel_url = getattr(settings, 'STRIPE_CANCEL_URL', 'http://localhost:3000/billing/cancel')
        self._credit_minimum_balance = getattr(settings, 'CREDIT_MINIMUM_BALANCE', '0.00')
        self._credit_cost_markup = getattr(settings, 'CREDIT_COST_MARKUP', '1.0')

    @property
    def stripe_secret_key(self):
        return self._stripe_secret_key

    @property
    def stripe_webhook_secret(self):
        return self._stripe_webhook_secret

    @property
    def stripe_success_url(self):
        return self._stripe_success_url

    @property
    def stripe_cancel_url(self):
        return self._stripe_cancel_url

    @property
    def credit_minimum_balance(self):
        return self._credit_minimum_balance

    @property
    def credit_cost_markup(self):
        return self._credit_cost_markup


billing_settings = BillingSettings()


def reload_billing_settings(*args, **kwargs):
    global billing_settings
    setting = kwargs.get("setting")
    if setting in [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_SUCCESS_URL",
        "STRIPE_CANCEL_URL",
        "CREDIT_MINIMUM_BALANCE",
        "CREDIT_COST_MARKUP",
    ]:
        billing_settings = BillingSettings()


setting_changed.connect(reload_billing_settings)
