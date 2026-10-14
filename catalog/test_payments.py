import uuid,json,hmac,hashlib,time
from types import SimpleNamespace
from unittest.mock import patch
from decimal import Decimal
from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient
from .payment_models import StripeSettings,Donor,PaymentOrder,StripeEvent,PaymentItem
from .stripe_gateway import encrypt,decrypt
from .payment_admin import StripeSettingsForm

class PaymentTests(TestCase):
    def setUp(self):
        cache.clear();self.client=APIClient();self.request_id=str(uuid.uuid4())
    def data(self):return {'request_id':self.request_id,'purpose':'donation','reference':'general','amount':'25.00','first_name':'Test','last_name':'Donor','email':'donor@example.com','anonymous':True,'comment':'Test'}
    def config(self):return StripeSettings.objects.create(enabled=True,mode='test',test_secret_ciphertext=encrypt('sk_test_fixture'),test_webhook_ciphertext=encrypt('whsec_fixture'))
    def event(self,order,event_id='evt_fixture',amount=2500,event_type='checkout.session.completed',paid=True):
        return {'id':event_id,'type':event_type,'livemode':False,'data':{'object':{'id':'cs_fixture','metadata':{'order_id':str(order.id)},'amount_total':amount,'currency':'cad','payment_status':'paid' if paid else 'unpaid','payment_intent':'pi_fixture'}}}
    def webhook(self,event,secret='whsec_fixture'):
        raw=json.dumps(event).encode();timestamp=int(time.time());digest=hmac.new(secret.encode(),str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return self.client.post('/api/payments/stripe/webhook/',raw,content_type='application/json',HTTP_STRIPE_SIGNATURE=f't={timestamp},v1={digest}')
    def test_unconfigured_saves_request_without_claiming_payment(self):
        for _ in range(2):
            response=self.client.post('/api/payments/checkout/',self.data(),format='json');self.assertEqual(response.status_code,202);self.assertFalse(response.json()['payment_ready'])
        self.assertEqual(Donor.objects.count(),1);self.assertEqual(PaymentOrder.objects.count(),1);self.assertEqual(PaymentOrder.objects.get().status,'registered')
    def test_reused_key_with_changed_amount_is_rejected(self):
        self.client.post('/api/payments/checkout/',self.data(),format='json');data=self.data();data['amount']='50.00';self.assertEqual(self.client.post('/api/payments/checkout/',data,format='json').status_code,409)
    def test_invalid_amount_and_email_are_rejected(self):
        for amount in ['0','-10','1.001','100001']:
            data=self.data();data['amount']=amount;self.assertEqual(self.client.post('/api/payments/checkout/',data,format='json').status_code,400)
        self.assertFalse(PaymentOrder.objects.exists())
    @patch('catalog.payments.client')
    def test_checkout_and_private_status(self,factory):
        self.config();factory.return_value.v1.checkout.sessions.create.return_value=SimpleNamespace(id='cs_fixture',url='https://checkout.stripe.com/c/pay/fixture',expires_at=int(time.time())+3600,livemode=False)
        response=self.client.post('/api/payments/checkout/',self.data(),format='json');self.assertEqual(response.status_code,200)
        order=PaymentOrder.objects.get();self.assertEqual(order.status,'pending');self.assertEqual(order.amount,Decimal('25'))
        args=factory.return_value.v1.checkout.sessions.create.call_args.args
        self.assertEqual(args[0]['line_items'][0]['price_data']['unit_amount'],2500);self.assertIn('idempotency_key',args[1])
        status=self.client.get(f'/api/payments/status/{order.pk}/').json();self.assertNotIn('email',status);self.assertNotIn('first_name',status)
    def test_signed_webhook_is_only_payment_confirmation(self):
        self.config();order=PaymentOrder.objects.create(request_id=uuid.uuid4(),donor=Donor.objects.create(email='test@example.com',first_name='Test'),first_name='Test',purpose='donation',title='Donation',amount=25,mode='test',status='pending',stripe_session_id='cs_fixture')
        event=self.event(order)
        self.assertEqual(self.webhook(event).status_code,200);self.assertEqual(self.webhook(event).status_code,200)
        order.refresh_from_db();self.assertEqual(order.status,'paid');self.assertEqual(StripeEvent.objects.count(),1)
        self.assertEqual(self.webhook(self.event(order,'evt_expire',event_type='checkout.session.expired',paid=False)).status_code,200);order.refresh_from_db();self.assertEqual(order.status,'paid')
    def test_forged_signature_and_amount_mismatch_are_rejected(self):
        self.config();order=PaymentOrder.objects.create(request_id=uuid.uuid4(),donor=Donor.objects.create(email='test@example.com',first_name='Test'),first_name='Test',purpose='donation',title='Donation',amount=25,mode='test',status='pending')
        self.assertEqual(self.webhook(self.event(order),secret='wrong').status_code,400)
        self.assertEqual(self.webhook(self.event(order,amount=100)).status_code,400);order.refresh_from_db();self.assertEqual(order.status,'pending')
    def test_secrets_are_encrypted_and_not_rendered(self):
        config=self.config();self.assertNotIn('sk_test_fixture',config.test_secret_ciphertext);self.assertEqual(decrypt(config.test_secret_ciphertext),'sk_test_fixture')
        form=StripeSettingsForm(instance=config);self.assertNotIn('sk_test_fixture',str(form));self.assertNotIn('whsec_fixture',str(form))
    def test_settings_cannot_enable_without_credentials(self):
        form=StripeSettingsForm(data={'enabled':True,'mode':'test','frontend_origin':'https://site-pearl-one-38.vercel.app','donations_enabled':True});self.assertFalse(form.is_valid())
    @patch('catalog.payments.client')
    def test_custom_item_price_cannot_be_changed_by_browser(self,factory):
        config=self.config();config.other_payments_enabled=True;config.save()
        PaymentItem.objects.create(slug='workshop',title='Workshop',amount=75)
        factory.return_value.v1.checkout.sessions.create.return_value=SimpleNamespace(id='cs_fixture',url='https://checkout.stripe.com/c/pay/fixture',expires_at=int(time.time())+3600,livemode=False)
        data=self.data();data.update(purpose='other',reference='workshop',amount='1.00')
        self.assertEqual(self.client.post('/api/payments/checkout/',data,format='json').status_code,200)
        self.assertEqual(PaymentOrder.objects.get().amount,Decimal('75'))
        self.assertEqual(self.client.get('/api/payments/items/other/workshop/').json()['amount'],'75.00')
    def test_unpaid_completed_event_never_marks_order_paid(self):
        self.config();order=PaymentOrder.objects.create(request_id=uuid.uuid4(),donor=Donor.objects.create(email='test@example.com',first_name='Test'),first_name='Test',purpose='donation',title='Donation',amount=25,mode='test',status='pending')
        self.assertEqual(self.webhook(self.event(order,paid=False)).status_code,200);order.refresh_from_db();self.assertEqual(order.status,'pending')
