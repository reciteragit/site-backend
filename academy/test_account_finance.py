import uuid
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from catalog.payment_models import Donor, PaymentOrder
from .models import Order
from .tests import fixture


class AccountFinanceTests(TestCase):
    def setUp(self):
        self.user, _, _, _, _, self.api = fixture()
        self.donor = Donor.objects.create(email=self.user.email, first_name='Learner')

    def order(self, **values):
        data = dict(user=self.user,email=self.user.email,request_id=uuid.uuid4(),amount=Decimal('24'),subtotal=30,discount_amount=6,currency='CAD',mode='live',status='paid',expires_at=timezone.now()+timedelta(minutes=30))
        data.update(values)
        return Order.objects.create(**data)

    def purchase(self, **values):
        data = dict(buyer=self.user,donor=self.donor,first_name='Learner',request_id=uuid.uuid4(),purpose='course',reference='test-course',title='Quran course',amount=Decimal('5'),subtotal=5,currency='CAD',mode='live',status='paid')
        data.update(values)
        return PaymentOrder.objects.create(**data)

    def test_scoped_totals_combine_courses_and_classes_without_test_or_email_matching(self):
        self.order()
        self.order(status='pending',amount=30,discount_amount=0)
        self.order(mode='test',amount=999)
        self.purchase()
        self.purchase(currency='USD',amount=7,subtotal=7)
        unlinked=self.purchase(buyer=None,amount=888)
        other = get_user_model().objects.create_user('finance-other',email='other@example.com')
        self.order(user=other,amount=777)
        self.purchase(buyer=other,amount=666)
        response = self.api.get('/api/academy/account/finance/')
        self.assertEqual(response.status_code,200)
        totals = {r['currency']:r for r in response.data['totals']}
        self.assertEqual(totals['CAD']['paid'],'29.00')
        self.assertEqual(totals['CAD']['pending'],'30.00')
        self.assertEqual(totals['CAD']['saved'],'6.00')
        self.assertEqual(totals['CAD']['paid_count'],2)
        self.assertEqual(totals['USD']['paid'],'7.00')
        self.assertEqual(response.data['total_count'],5)
        self.assertEqual(len(response.data['transactions']),5)
        self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertNotIn(str(unlinked.pk),[row['id'] for row in response.data['transactions']])
        self.assertNotContains(response,'stripe_session_id')

    def test_authentication_is_required(self):
        self.assertEqual(APIClient().get('/api/academy/account/finance/').status_code,401)

    def test_history_limit_does_not_truncate_summary(self):
        for _ in range(101):self.order(amount=1,subtotal=1,discount_amount=0)
        response = self.api.get('/api/academy/account/finance/')
        self.assertEqual(len(response.data['transactions']),100)
        self.assertTrue(response.data['has_more'])
        self.assertEqual(response.data['totals'][0]['paid'],'101.00')
