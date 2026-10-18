import hashlib
import os
import stripe
from django.core.management.base import BaseCommand, CommandError
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import encrypt, valid_origin

EVENTS = ["checkout.session.completed", "checkout.session.async_payment_succeeded",
          "checkout.session.async_payment_failed", "checkout.session.expired"]

class Command(BaseCommand):
    help = "Connect the existing Stripe donation settings and provision its webhook"

    def handle(self, *args, **options):
        if os.getenv("STRIPE_AUTOCONFIGURE", "false").lower() != "true":
            self.stdout.write("Automatic Stripe setup is disabled; existing settings preserved.")
            return
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if not key:
            self.stdout.write("Stripe secret key is not configured; existing settings preserved.")
            return
        if key.startswith("sk_test_"):
            mode = "test"
        elif key.startswith("sk_live_"):
            mode = "live"
        else:
            raise CommandError("Use a Stripe test or live Secret API key in STRIPE_SECRET_KEY")
        origin = os.getenv("STRIPE_FRONTEND_ORIGIN", "https://site-pearl-one-38.vercel.app").rstrip("/")
        url = os.getenv("STRIPE_WEBHOOK_URL", "https://site-backend-one.vercel.app/api/payments/stripe/webhook/")
        from urllib.parse import urlsplit
        endpoint_url = urlsplit(url)
        if not valid_origin(origin) or endpoint_url.scheme != "https" or not endpoint_url.hostname or endpoint_url.username or endpoint_url.password or endpoint_url.query or endpoint_url.fragment:
            raise CommandError("Configure valid public HTTPS frontend and webhook addresses")
        config = StripeSettings.objects.first() or StripeSettings()
        sdk = stripe.StripeClient(key, max_network_retries=1, http_client=stripe.RequestsClient(timeout=15))
        try:
            account = sdk.v1.accounts.retrieve_current()
            if mode == "live" and not account.charges_enabled:
                raise CommandError("Stripe requires account activation before live payments can be enabled")
            endpoint_id = getattr(config, f"{mode}_webhook_id")
            same_account = getattr(config, f"{mode}_account_id") == account.id
            stored_secret = getattr(config, f"{mode}_webhook_ciphertext")
            if endpoint_id and same_account and stored_secret:
                endpoint = sdk.v1.webhook_endpoints.retrieve(endpoint_id)
                sdk.v1.webhook_endpoints.update(endpoint.id, {"url": url, "disabled": False, "enabled_events": EVENTS})
            else:
                digest = hashlib.sha256(f"{url}:{account.id}:{mode}".encode()).hexdigest()[:32]
                endpoint = sdk.v1.webhook_endpoints.create({
                    "url": url, "enabled_events": EVENTS,
                    "description": "Recitera donation payment confirmation",
                    "metadata": {"application": "recitera", "purpose": "donations"},
                }, options={"idempotency_key": f"recitera-donations-{digest}"})
                setattr(config, f"{mode}_webhook_ciphertext", encrypt(endpoint.secret))
            setattr(config, f"{mode}_secret_ciphertext", encrypt(key))
            setattr(config, f"{mode}_webhook_id", endpoint.id)
            setattr(config, f"{mode}_account_id", account.id)
            config.frontend_origin = origin
            config.donations_enabled = True
            # Configuring sandbox credentials must not switch off an existing
            # active live checkout or alter other payment-section settings.
            if not (config.enabled and config.mode == "live" and mode == "test"):
                config.mode = mode
                config.enabled = True
            config.save()
            self.stdout.write(self.style.SUCCESS(f"Stripe {mode} donation connection and webhook configured; secrets stored encrypted."))
        except stripe.StripeError:
            raise CommandError("Stripe setup failed. Check the API key, account access and webhook permissions.") from None
