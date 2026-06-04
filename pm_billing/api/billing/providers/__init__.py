"""Payment provider factory."""
from django.conf import settings


def get_payment_provider():
    """Return the active payment provider instance."""
    provider = getattr(settings, 'PAYMENT_PROVIDER', 'stripe')
    if provider == 'paypal':
        from .paypal import PayPalProvider
        return PayPalProvider()
    from .stripe import StripeProvider
    return StripeProvider()
