from django.core.management.base import BaseCommand,CommandError
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import ready
class Command(BaseCommand):
    help='Enable paid recorded-course checkout after verifying existing Stripe readiness.'
    def handle(self,*args,**options):
        config=StripeSettings.objects.first()
        if not ready(config):raise CommandError('Connect Stripe and its webhook before enabling paid course checkout.')
        config.courses_enabled=True;config.save(update_fields=['courses_enabled'])
        self.stdout.write('Recorded-course and package checkout enabled; no demo courses or videos created.')
