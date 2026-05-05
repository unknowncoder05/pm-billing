from django.apps import AppConfig


class PMBillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pm_billing'
    verbose_name = 'PM Billing'

    def ready(self):
        from .api.billing import signals  # noqa: F401
