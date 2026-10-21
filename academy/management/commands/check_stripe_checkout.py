from django.core.management.base import BaseCommand, CommandError
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import client, ready
from django.utils import timezone
from datetime import timedelta
import stripe
import uuid

class Command(BaseCommand):
    help = 'Probe hosted Stripe Checkout without charging, then immediately expire the diagnostic session.'
    def add_arguments(self, parser):
        parser.add_argument('--retry-pending', action='store_true')

    def handle(self, *args, **options):
        config = StripeSettings.objects.first()
        if not ready(config):
            raise CommandError('Checkout probe: Stripe configuration is not ready.')
        gateway = client(config)
        reference = 'recitera-diagnostic-'+uuid.uuid4().hex
        try:
            session = gateway.v1.checkout.sessions.create({'mode':'payment','customer_email':'info@recitera.com','client_reference_id':reference,'metadata':{'diagnostic_reference':reference},'expires_at':int((timezone.now()+timedelta(minutes=40)).timestamp()),'line_items':[{'price_data':{'currency':'cad','unit_amount':3000,'product_data':{'name':'Recitera checkout connectivity check'}},'quantity':1}],'success_url':config.frontend_origin.rstrip('/')+'/account','cancel_url':config.frontend_origin.rstrip('/')+'/cart'}, {'idempotency_key':reference})
            valid = bool(session.url and session.url.startswith('https://checkout.stripe.com/')) and bool(session.livemode) == (config.mode == 'live')
            gateway.v1.checkout.sessions.expire(session.id)
            if not valid:
                raise CommandError('Checkout probe: session mode or destination validation failed.')
            self.stdout.write('Checkout probe: hosted session created and expired; no charge collected.')
        except stripe.StripeError as exc:
            if isinstance(exc, stripe.InvalidRequestError):
                self.stdout.write('Checkout method diagnostic: '+str(exc))
            # Only structured codes: never log keys, customer data or checkout URLs.
            raise CommandError(f'Checkout probe: type={type(exc).__name__} code={getattr(exc,"code",None)} param={getattr(exc,"param",None)}') from None

        if options.get('retry_pending'):
            from academy.models import Order
            from academy.services import expire_holds
            from academy.views import Checkout
            from rest_framework.test import APIRequestFactory, force_authenticate
            expire_holds()
            orders = list(Order.objects.filter(status='held', checkout_url='', expires_at__gt=timezone.now()).select_related('user')[:10])
            self.stdout.write(f'Checkout recovery: {len(orders)} active unprepared reservations.')
            for order in orders:
                request = APIRequestFactory().post('/api/academy/checkout/', {'request_id':str(order.request_id),'timezone':'UTC'},format='json')
                force_authenticate(request,user=order.user)
                response = Checkout.as_view()(request)
                self.stdout.write(f'Checkout recovery: status={response.status_code} prepared={bool(response.data.get("checkout_url"))}')
