"""Billing admin — CreditBalance with grant action, read-only CreditTransaction."""
from decimal import Decimal

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import BillingSettings, CostTemplate, CreditBalance, CreditTransaction
from .services.credits import add_credits


@admin.register(BillingSettings)
class BillingSettingsAdmin(admin.ModelAdmin):
    """Singleton admin for site-wide billing configuration."""

    fields = ['welcome_bonus', 'warning_threshold', 'critical_threshold', 'updated_at']
    readonly_fields = ['updated_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = BillingSettings.get()
        return HttpResponseRedirect(
            reverse('admin:pm_billing_billingsettings_change', args=[obj.pk])
        )


@admin.register(CostTemplate)
class CostTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'operation_type', 'markup', 'price_per_unit', 'is_active', 'updated_at']
    list_filter = ['is_active', 'operation_type']
    list_editable = ['markup', 'price_per_unit', 'is_active']
    search_fields = ['name', 'operation_type']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CreditBalance)
class CreditBalanceAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'total_deposited', 'total_spent', 'updated_at', 'grant_link']
    list_filter = ['updated_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'balance', 'total_deposited', 'total_spent', 'created_at', 'updated_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def grant_link(self, obj):
        url = reverse('admin:pm_billing_creditbalance_grant', args=[obj.pk])
        return format_html('<a href="{}">Grant Credits</a>', url)
    grant_link.short_description = 'Grant'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:pk>/grant/',
                self.admin_site.admin_view(self.grant_credits_view),
                name='pm_billing_creditbalance_grant',
            ),
        ]
        return custom_urls + urls

    def grant_credits_view(self, request, pk):
        balance_obj = self.get_object(request, pk)
        if balance_obj is None:
            return HttpResponseRedirect(reverse('admin:pm_billing_creditbalance_changelist'))

        if request.method == 'POST':
            amount = request.POST.get('amount', '0')
            description = request.POST.get('description', '')
            try:
                amount = Decimal(amount)
                if amount <= 0:
                    raise ValueError("Amount must be positive")
                add_credits(
                    user=balance_obj.user,
                    amount=amount,
                    transaction_type='admin_grant',
                    description=description or f'Admin grant by {request.user.username}',
                )
                self.message_user(
                    request,
                    f"Successfully granted ${amount:.2f} to {balance_obj.user}."
                )
                return HttpResponseRedirect(
                    reverse('admin:pm_billing_creditbalance_changelist')
                )
            except (ValueError, Exception) as e:
                self.message_user(request, f"Error: {e}", level='error')

        context = {
            **self.admin_site.each_context(request),
            'title': f'Grant Credits to {balance_obj.user}',
            'balance_obj': balance_obj,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/billing/grant_credits.html', context)


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'amount', 'balance_after',
        'transaction_type', 'context_type', 'context_id', 'reference_id', 'created_at',
    ]
    list_filter = ['transaction_type', 'context_type', 'created_at']
    search_fields = ['user__username', 'user__email', 'reference_id', 'description']
    readonly_fields = [
        'user', 'amount', 'balance_after', 'transaction_type',
        'reference_id', 'description', 'stripe_payment_intent_id',
        'stripe_checkout_session_id', 'context_type', 'context_id', 'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
