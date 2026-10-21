from django.core.management.base import BaseCommand, CommandError
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import client, ready
from django.utils import timezone
from datetime import timedelta
import stripe

class Command(BaseCommand):
    help = 'Probe hosted Stripe Checkout without charging, then immediately expire the diagnostic session.'
    def handle(self, *args, **options):
        config = StripeSettings.objects.first()
        if not ready(config):
            raise CommandError('Checkout probe: Stripe configuration is not ready.')
        gateway = client(config)
        try:
            session = gateway.v1.checkout.sessions.create({'mode':'payment','payment_method_types':['card'],'expires_at':int((timezone.now()+timedelta(minutes=40)).timestamp()),'line_items':[{'price_data':{'currency':'cad','unit_amount':3000,'product_data':{'name':'Recitera checkout connectivity check'}},'quantity':1}],'success_url':config.frontend_origin.rstrip('/')+'/account','cancel_url':config.frontend_origin.rstrip('/')+'/cart'})
            gateway.v1.checkout.sessions.expire(session.id)
            self.stdout.write('Checkout probe: hosted session created and expired; no charge collected.')
        except stripe.StripeError as exc:
            if isinstance(exc, stripe.InvalidRequestError) and exc.param == 'payment_method_types':
                self.stdout.write('Checkout method diagnostic: '+str(exc))
            # Only structured codes: never log keys, customer data or checkout URLs.
            raise CommandError(f'Checkout probe: type={type(exc).__name__} code={getattr(exc,"code",None)} param={getattr(exc,"param",None)}') from None
