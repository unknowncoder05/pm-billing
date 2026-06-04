"""Abstract payment provider interface."""
from abc import ABC, abstractmethod


class PaymentProviderError(Exception):
    """User-safe payment provider failure."""

    def __init__(
        self,
        message,
        *,
        code='payment_provider_error',
        status_code=502,
        provider='',
        diagnostics=None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.provider = provider
        self.diagnostics = diagnostics or {}

    def as_response_data(self):
        data = {
            'error': self.message,
            'code': self.code,
        }
        if self.provider:
            data['payment_provider'] = self.provider
        return data


class PaymentProvider(ABC):
    """Interface implemented by hosted checkout providers."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when required provider credentials are configured."""

    @abstractmethod
    def create_checkout(self, user, amount, success_url: str, cancel_url: str) -> dict:
        """Create a hosted checkout session/order."""

    @abstractmethod
    def handle_webhook(self, request):
        """Validate and process an incoming webhook."""
