"""Billing serializers."""
from rest_framework import serializers

from ..models import BillingSettings, CreditBalance, CreditTransaction


class CreditBalanceSerializer(serializers.ModelSerializer):
    """Serializer for user's credit balance, including UI thresholds from BillingSettings."""

    warning_threshold = serializers.SerializerMethodField()
    critical_threshold = serializers.SerializerMethodField()

    class Meta:
        model = CreditBalance
        fields = [
            'balance',
            'total_deposited',
            'total_spent',
            'created_at',
            'updated_at',
            'warning_threshold',
            'critical_threshold',
        ]
        read_only_fields = fields

    def get_warning_threshold(self, obj):
        return str(BillingSettings.get().warning_threshold)

    def get_critical_threshold(self, obj):
        return str(BillingSettings.get().critical_threshold)


class CreditTransactionSerializer(serializers.ModelSerializer):
    """Serializer for credit transaction ledger entries."""

    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display',
        read_only=True,
    )

    class Meta:
        model = CreditTransaction
        fields = [
            'id',
            'amount',
            'balance_after',
            'transaction_type',
            'transaction_type_display',
            'reference_id',
            'description',
            'created_at',
        ]
        read_only_fields = fields


class CheckoutSessionCreateSerializer(serializers.Serializer):
    """Serializer for creating a Stripe Checkout session."""

    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=1,
        max_value=1000,
        help_text="USD amount to purchase (1–1000)",
    )
    success_url = serializers.URLField(required=False)
    cancel_url = serializers.URLField(required=False)
