from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AbstractCostTemplate(models.Model):
    """Per-operation pricing rules."""

    OPERATION_CHOICES = [
        ('generic', _('Generic Operation')),
    ]

    name = models.CharField(max_length=100)
    operation_type = models.CharField(
        max_length=50,
        choices=OPERATION_CHOICES,
        unique=True,
    )
    markup = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('1.0'),
        help_text=_("Multiplier applied on top of the base cost (1.0 = no markup)"),
    )
    price_per_unit = models.DecimalField(
        max_digits=8,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_("Fixed price per unit in USD (optional; use for flat-rate billing)"),
    )
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        verbose_name = _('Cost Template')
        verbose_name_plural = _('Cost Templates')

    def __str__(self):
        return f"{self.name} ({self.operation_type}) ×{self.markup}"


class AbstractBillingSettings(models.Model):
    """Singleton row for site-wide billing configuration."""

    welcome_bonus = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_("USD credited to every new user on signup. Set to 0 to disable."),
    )
    warning_threshold = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('5.00'),
        help_text=_("Balance falls below this → yellow warning indicator in the UI."),
    )
    critical_threshold = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text=_("Balance falls below this → red critical indicator in the UI."),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        verbose_name = _('Billing Settings')
        verbose_name_plural = _('Billing Settings')

    def __str__(self):
        return (
            f"Billing Settings — bonus ${self.welcome_bonus}, "
            f"warn ${self.warning_threshold}, crit ${self.critical_threshold}"
        )

    @classmethod
    def get(cls):
        """Return (or create) the single settings instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AbstractCreditBalance(models.Model):
    """Tracks current USD credit balance for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_balance',
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=0,
        help_text=_("Current USD credit balance"),
    )
    total_deposited = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_("Total USD deposited over lifetime"),
    )
    total_spent = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=0,
        help_text=_("Total USD spent over lifetime"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        verbose_name = _('Credit Balance')
        verbose_name_plural = _('Credit Balances')

    def __str__(self):
        return f"{self.user} — ${self.balance:.2f}"


class AbstractCreditTransaction(models.Model):
    """Append-only ledger of all credit changes."""

    TRANSACTION_TYPES = [
        ('purchase',            _('Purchase')),
        ('admin_grant',         _('Admin Grant')),
        ('execution_deduction', _('Execution Deduction')),
        ('chat_deduction',      _('Chat Deduction')),
        ('refund',              _('Refund')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_transactions',
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        help_text=_("Positive = credit added, negative = credit deducted"),
    )
    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        help_text=_("User's balance after this transaction"),
    )
    transaction_type = models.CharField(
        max_length=30,
        choices=TRANSACTION_TYPES,
    )
    reference_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_("Optional external reference (e.g. execution ID, order ID)"),
    )
    description = models.TextField(
        blank=True,
        default='',
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
    )
    stripe_checkout_session_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_("Used for idempotency on webhook processing"),
    )
    context_type = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text=_("Optional label for the entity that triggered this transaction"),
    )
    context_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("Optional PK of the entity that triggered this transaction"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        verbose_name = _('Credit Transaction')
        verbose_name_plural = _('Credit Transactions')
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{self.user} {sign}{self.amount:.6f} ({self.transaction_type})"
