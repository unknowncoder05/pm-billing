"""Billing signals — auto-create CreditBalance and grant welcome bonus on user creation."""
import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BillingSettings, CreditBalance

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_credit_balance(sender, instance, created, **kwargs):
    """Create a CreditBalance record and grant a welcome bonus when a new user is created."""
    if created:
        CreditBalance.objects.get_or_create(user=instance)
        try:
            from .services.credits import add_credits
            bonus = BillingSettings.get().welcome_bonus
            if bonus > 0:
                add_credits(
                    instance,
                    bonus,
                    transaction_type='admin_grant',
                    description=f'Welcome bonus — ${bonus} free credits',
                )
                logger.info(f"Granted ${bonus} welcome bonus to new user {instance.id}")
        except Exception as e:
            logger.error(f"Failed to grant welcome bonus to user {instance.id}: {e}")
