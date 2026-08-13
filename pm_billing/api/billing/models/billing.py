from django.db import models
from pm_utils.api.utils.models import BaseModel
from pm_billing.api.billing.abstract_models import (
    AbstractCostTemplate,
    AbstractBillingSettings,
    AbstractCreditBalance,
    AbstractPayPalCheckoutSession,
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
            models.Index(fields=['user', '-created_at'], name='pm_billing__user_id_39d832_idx'),
            models.Index(fields=['transaction_type'], name='pm_billing__transac_994705_idx'),
            models.Index(fields=['stripe_payment_intent_id'], name='pm_billing__stripe__c451c1_idx'),
            models.Index(fields=['stripe_checkout_session_id'], name='pm_billing__stripe__a1277b_idx'),
            models.Index(fields=['external_order_id'], name='pm_billing__externa_9677ed_idx'),
            models.Index(fields=['context_type', 'context_id'], name='pm_billing__context_f3d273_idx'),
        ]


class PayPalCheckoutSession(AbstractPayPalCheckoutSession):
    class Meta(AbstractPayPalCheckoutSession.Meta):
        abstract = False
        app_label = 'pm_billing'
        indexes = [
            models.Index(fields=['user', '-created_at'], name='pm_billing__user_id_f4d297_idx'),
            models.Index(fields=['status'], name='pm_billing__status_03363d_idx'),
        ]
