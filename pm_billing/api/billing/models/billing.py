from django.db import models
from pm_utils.api.utils.models import BaseModel
from .abstract_models import (
    AbstractCostTemplate,
    AbstractBillingSettings,
    AbstractCreditBalance,
    AbstractCreditTransaction,
)


class CostTemplate(BaseModel, AbstractCostTemplate):
    class Meta(AbstractCostTemplate.Meta):
        abstract = False
        app_label = 'pm_billing'


class BillingSettings(AbstractBillingSettings):
    class Meta(AbstractBillingSettings.Meta):
        abstract = False
        app_label = 'pm_billing'


class CreditBalance(BaseModel, AbstractCreditBalance):
    class Meta(AbstractCreditBalance.Meta):
        abstract = False
        app_label = 'pm_billing'


class CreditTransaction(AbstractCreditTransaction):
    class Meta(AbstractCreditTransaction.Meta):
        abstract = False
        app_label = 'pm_billing'
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['transaction_type']),
            models.Index(fields=['stripe_payment_intent_id']),
            models.Index(fields=['stripe_checkout_session_id']),
            models.Index(fields=['context_type', 'context_id']),
        ]
