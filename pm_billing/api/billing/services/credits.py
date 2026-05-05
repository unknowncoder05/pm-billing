"""Core billing services for credit management."""
import logging
from decimal import Decimal

from django.db import transaction

from ..conf import billing_settings
from ..exceptions import InsufficientCreditsError
from ..models import CreditBalance, CreditTransaction

logger = logging.getLogger(__name__)


def check_user_balance(user):
    """Check if user has sufficient credits to perform an action."""
    balance_obj, _ = CreditBalance.objects.get_or_create(user=user)

    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return balance_obj

    minimum = Decimal(str(billing_settings.credit_minimum_balance))

    if balance_obj.balance <= minimum:
        raise InsufficientCreditsError(
            f"Insufficient credits. Current balance: ${balance_obj.balance:.2f}. "
            f"Please add funds to continue."
        )
    return balance_obj


def add_credits(
    user,
    amount,
    transaction_type='purchase',
    description='',
    reference_id='',
    stripe_payment_intent_id='',
    stripe_checkout_session_id='',
):
    """Add credits to a user's balance atomically."""
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("Amount must be positive for add_credits")

    with transaction.atomic():
        balance_obj, _ = CreditBalance.objects.select_for_update().get_or_create(
            user=user
        )
        balance_obj.balance += amount
        balance_obj.total_deposited += amount
        balance_obj.save(update_fields=['balance', 'total_deposited', 'updated_at'])

        txn = CreditTransaction.objects.create(
            user=user,
            amount=amount,
            balance_after=balance_obj.balance,
            transaction_type=transaction_type,
            reference_id=str(reference_id),
            description=description,
            stripe_payment_intent_id=stripe_payment_intent_id,
            stripe_checkout_session_id=stripe_checkout_session_id,
        )

    logger.info(
        f"Added ${amount:.6f} to user {user.id} "
        f"(type={transaction_type}, new_balance=${balance_obj.balance:.6f})"
    )
    return txn


def _get_markup(operation_type=None):
    """Return the markup multiplier for an operation type."""
    if operation_type:
        try:
            from ..models import CostTemplate
            tpl = CostTemplate.objects.get(operation_type=operation_type, is_active=True)
            return tpl.markup
        except Exception:
            pass
        from django.conf import settings
        env_key = f"{operation_type.upper()}_COST_MARKUP"
        op_markup = getattr(settings, env_key, None)
        if op_markup is not None:
            return Decimal(str(op_markup))
    return Decimal(str(billing_settings.credit_cost_markup))


def deduct_credits(
    user,
    amount,
    transaction_type='execution_deduction',
    description='',
    reference_id='',
    context_type='',
    context_id=None,
    operation_type=None,
):
    """Deduct credits from a user's balance atomically."""
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("Amount must be positive for deduct_credits")

    markup = _get_markup(operation_type)
    effective_amount = amount * markup

    with transaction.atomic():
        balance_obj, _ = CreditBalance.objects.select_for_update().get_or_create(
            user=user
        )
        balance_obj.balance -= effective_amount
        balance_obj.total_spent += effective_amount
        balance_obj.save(update_fields=['balance', 'total_spent', 'updated_at'])

        txn = CreditTransaction.objects.create(
            user=user,
            amount=-effective_amount,
            balance_after=balance_obj.balance,
            transaction_type=transaction_type,
            reference_id=str(reference_id),
            description=description,
            context_type=context_type or '',
            context_id=context_id,
        )

    logger.info(
        f"Deducted ${effective_amount:.6f} from user {user.id} "
        f"(type={transaction_type}, new_balance=${balance_obj.balance:.6f})"
    )
    return txn
