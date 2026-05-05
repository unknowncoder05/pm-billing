"""Billing exceptions."""


class InsufficientCreditsError(Exception):
    """Raised when a user does not have enough credits to perform an action."""

    def __init__(self, message="Insufficient credits. Please add funds to continue."):
        self.message = message
        super().__init__(self.message)
