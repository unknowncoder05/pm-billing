"""URL routing for the billing app."""
from django.urls import path

from .views.billing import (
    BalanceView,
    CheckoutCaptureView,
    CheckoutView,
    PayPalWebhookView,
    StripeWebhookView,
    TransactionListView,
)

urlpatterns = [
    path('billing/balance/',          BalanceView.as_view(),          name='billing-balance'),
    path('billing/transactions/',     TransactionListView.as_view(),  name='billing-transactions'),
    path('billing/checkout/',         CheckoutView.as_view(),         name='billing-checkout'),
    path('billing/checkout/capture/', CheckoutCaptureView.as_view(),  name='billing-checkout-capture'),
    path('billing/webhook/',          StripeWebhookView.as_view(),    name='billing-webhook-stripe'),
    path('billing/webhook/paypal/',   PayPalWebhookView.as_view(),    name='billing-webhook-paypal'),
]
