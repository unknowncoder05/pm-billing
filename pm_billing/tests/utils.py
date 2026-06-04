"""Shared test helpers for pm-billing."""
from unittest import skipUnless

from django.conf import settings


requires_pm_billing_app = skipUnless(
    'pm_billing' in settings.INSTALLED_APPS,
    'pm_billing app is not installed in this Django settings module',
)
