# Generated manually for PayPal provider support.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pm_billing', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='credittransaction',
            name='external_order_id',
            field=models.CharField(blank=True, default='', help_text='Provider-agnostic order/session ID for idempotency', max_length=255),
        ),
        migrations.AddField(
            model_name='credittransaction',
            name='payment_provider',
            field=models.CharField(blank=True, default='stripe', help_text='Which payment provider processed this transaction', max_length=30),
        ),
        migrations.AddIndex(
            model_name='credittransaction',
            index=models.Index(fields=['external_order_id'], name='pm_billing__externa_9677ed_idx'),
        ),
        migrations.CreateModel(
            name='PayPalCheckoutSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_id', models.CharField(max_length=255, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='USD', max_length=3)),
                ('status', models.CharField(choices=[('created', 'Created'), ('captured', 'Captured'), ('credited', 'Credited'), ('failed', 'Failed')], default='created', max_length=20)),
                ('last_error', models.TextField(blank=True, default='')),
                ('diagnostics', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='paypal_checkout_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'PayPal Checkout Session',
                'verbose_name_plural': 'PayPal Checkout Sessions',
                'abstract': False,
                'indexes': [models.Index(fields=['user', '-created_at'], name='pm_billing__user_id_f4d297_idx'), models.Index(fields=['status'], name='pm_billing__status_03363d_idx')],
            },
        ),
    ]
