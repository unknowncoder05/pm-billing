# PM Billing

ProjectMaker shared billing and subscriptions package.

## Features
- Stripe integration
- PayPal Orders API checkout, capture, and webhook support
- Subscription management
- Credit/Balance system
- Multi-currency support via django-money

## Payment Provider Settings

Set `PAYMENT_PROVIDER` to `stripe` or `paypal`.

PayPal uses:
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_WEBHOOK_ID`
- `PAYPAL_ENVIRONMENT` (`live` or `sandbox`)
- `PAYPAL_SUCCESS_URL`
- `PAYPAL_CANCEL_URL`
