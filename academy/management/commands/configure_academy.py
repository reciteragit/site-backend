import os
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import ready

class Command(BaseCommand):
    help='Enable reserved class checkout only when explicitly configured and Stripe is ready.'
    def handle(self,*args,**options):
        call_command('import_teacher_accounts', stdout=self.stdout)
        if os.getenv('ACADEMY_PAYMENTS_ENABLED','false').lower()!='true':
            self.stdout.write('Academy payment setup not requested; existing settings preserved.');return
        config=StripeSettings.objects.first()
        if not ready(config):raise CommandError('Configure Stripe and its signed webhook before enabling class checkout.')
        if os.getenv('STRIPE_CHECKOUT_PROBE', 'false').lower() == 'true':
            call_command('check_stripe_checkout', retry_pending=os.getenv('STRIPE_CHECKOUT_RETRY_PENDING','false').lower()=='true', stdout=self.stdout)
        if not config.lessons_enabled:
            config.lessons_enabled=True;config.save(update_fields=['lessons_enabled'])
        self.stdout.write(f'Academy class checkout enabled in Stripe {config.mode} mode. Teachers still require approval and a classroom URL.')
