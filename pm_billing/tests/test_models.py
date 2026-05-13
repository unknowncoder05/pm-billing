from django.test import TestCase
from django.contrib.auth import get_user_model
from pm_billing.api.billing.models import CreditBalance, BillingSettings
from decimal import Decimal

User = get_user_model()

class BillingModelsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='billing@example.com',
            password='password123'
        )

    def test_credit_balance_creation_signal(self):
        # CreditBalance should be created automatically via signal
        # Note: In Modular template, pm_billing.signals is connected to User model
        balance = CreditBalance.objects.filter(user=self.user).first()
        self.assertIsNotNone(balance)
        self.assertEqual(balance.balance, Decimal('0.000000'))

    def test_billing_settings(self):
        # Use update_or_create or just update existing since it might be a singleton
        settings, created = BillingSettings.objects.update_or_create(
            id=1,
            defaults={'welcome_bonus': Decimal('10.00')}
        )
        self.assertEqual(settings.welcome_bonus, Decimal('10.00'))
