import os
from types import SimpleNamespace
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from .payment_models import StripeSettings
from .stripe_gateway import decrypt, encrypt, ready

@patch.dict(os.environ, {'STRIPE_AUTOCONFIGURE':'true','STRIPE_SECRET_KEY':'sk_test_fixture','STRIPE_FRONTEND_ORIGIN':'https://site-pearl-one-38.vercel.app','STRIPE_WEBHOOK_URL':'https://site-backend-one.vercel.app/api/payments/stripe/webhook/'})
class StripeAutomaticSetupTests(TestCase):
    def sdk(self, factory):
        sdk=factory.return_value
        sdk.v1.accounts.retrieve_current.return_value=SimpleNamespace(id='acct_fixture',charges_enabled=True)
        sdk.v1.webhook_endpoints.create.return_value=SimpleNamespace(id='we_fixture',secret='whsec_fixture')
        sdk.v1.webhook_endpoints.retrieve.return_value=SimpleNamespace(id='we_fixture')
        return sdk

    @patch('catalog.management.commands.configure_stripe.stripe.StripeClient')
    def test_configures_existing_settings_and_reuses_webhook(self, factory):
        original=StripeSettings.objects.create(courses_enabled=False,lessons_enabled=False,other_payments_enabled=True)
        sdk=self.sdk(factory)
        call_command('configure_stripe');call_command('configure_stripe')
        self.assertEqual(StripeSettings.objects.count(),1)
        config=StripeSettings.objects.get(pk=original.pk)
        self.assertTrue(ready(config));self.assertEqual(config.mode,'test')
        self.assertEqual(decrypt(config.test_secret_ciphertext),'sk_test_fixture')
        self.assertEqual(decrypt(config.test_webhook_ciphertext),'whsec_fixture')
        self.assertNotIn('whsec_fixture',config.test_webhook_ciphertext)
        self.assertEqual(sdk.v1.webhook_endpoints.create.call_count,1)
        self.assertTrue(config.other_payments_enabled)
        self.assertFalse(config.courses_enabled or config.lessons_enabled)

    @patch('catalog.management.commands.configure_stripe.stripe.StripeClient')
    def test_sandbox_setup_does_not_disable_an_active_live_account(self, factory):
        StripeSettings.objects.create(enabled=True,mode='live',live_secret_ciphertext=encrypt('sk_live_existing'),live_webhook_ciphertext=encrypt('whsec_existing'))
        self.sdk(factory);call_command('configure_stripe')
        config=StripeSettings.objects.get()
        self.assertEqual(config.mode,'live');self.assertTrue(ready(config))
        self.assertEqual(decrypt(config.live_secret_ciphertext),'sk_live_existing')
        self.assertEqual(decrypt(config.test_secret_ciphertext),'sk_test_fixture')

    @patch.dict(os.environ, {'STRIPE_SECRET_KEY':'sk_live_fixture'})
    @patch('catalog.management.commands.configure_stripe.stripe.StripeClient')
    def test_live_activation_requires_a_charge_enabled_account(self, factory):
        sdk=self.sdk(factory);sdk.v1.accounts.retrieve_current.return_value=SimpleNamespace(id='acct_fixture',charges_enabled=False)
        with self.assertRaises(CommandError):call_command('configure_stripe')
        self.assertFalse(StripeSettings.objects.exists());sdk.v1.webhook_endpoints.create.assert_not_called()

    @patch.dict(os.environ, {'STRIPE_AUTOCONFIGURE':'false'})
    @patch('catalog.management.commands.configure_stripe.stripe.StripeClient')
    def test_disabled_setup_leaves_admin_settings_unchanged(self, factory):
        config=StripeSettings.objects.create(enabled=False)
        call_command('configure_stripe');config.refresh_from_db()
        self.assertFalse(config.enabled);factory.assert_not_called()
