from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from academy.tests import fixture, stripe_session
from academy.models import Order, Booking, Slot
from catalog.models import Teacher, Course
from catalog.payment_models import PaymentItem, PaymentOrder
from .discount_models import DiscountCode
from .discounts import ProductLine, calculate_discount


class DiscountRulesTests(TestCase):
    def coupon(self,**fields):
        return DiscountCode.objects.create(code='SAVE20',name='Example',value=20,**fields)
    def line(self,amount='100',kind='teacher',pk=1):return ProductLine(kind,pk,Decimal(amount))
    def test_percentage_fixed_cap_and_exact_allocation(self):
        coupon=self.coupon()
        self.assertEqual(calculate_discount(' save20 ',[self.line()]).total,Decimal('80'))
        coupon.discount_type='fixed';coupon.value=Decimal('1');coupon.save()
        quote=calculate_discount(coupon.code,[self.line('1'),self.line('1',pk=2),self.line('1',pk=3)])
        self.assertEqual(quote.amounts,[Decimal('.66'),Decimal('.67'),Decimal('.67')])
        self.assertEqual(sum(quote.amounts),quote.total)
        coupon.value=1000;coupon.save();self.assertEqual(calculate_discount(coupon.code,[self.line()]).total,0)
    def test_scope_and_minimum_use_only_eligible_products(self):
        teacher=Teacher.objects.create(name='Example',slug='example',price=100,languages=['English'])
        coupon=self.coupon(all_products=False,minimum_amount=100)
        coupon.teachers.add(teacher)
        with self.assertRaises(ValidationError):calculate_discount(coupon.code,[self.line('99',pk=teacher.pk),self.line('500',pk=999)])
        quote=calculate_discount(coupon.code,[self.line('100',pk=teacher.pk),self.line('50',pk=999)])
        self.assertEqual(quote.total,130)
        coupon.minimum_basis='individual_product';coupon.save()
        with self.assertRaises(ValidationError):calculate_discount(coupon.code,[self.line('60',pk=teacher.pk),self.line('60',pk=teacher.pk)])
        quote=calculate_discount(coupon.code,[self.line('120',pk=teacher.pk),self.line('50',pk=teacher.pk)])
        self.assertEqual(quote.discount,24)
    def test_dates_personal_account_and_free_items(self):
        user=get_user_model().objects.create_user('eligible','eligible@example.com')
        coupon=self.coupon(allowed_user=user)
        with self.assertRaises(ValidationError):calculate_discount(coupon.code,[self.line()])
        self.assertEqual(calculate_discount(coupon.code,[self.line()],user).total,80)
        coupon.ends_at=timezone.now()-timedelta(seconds=1);coupon.save()
        with self.assertRaises(ValidationError):calculate_discount(coupon.code,[self.line()],user)
        coupon.ends_at=None;coupon.starts_at=timezone.now()+timedelta(days=1);coupon.save()
        with self.assertRaises(ValidationError):calculate_discount(coupon.code,[self.line()],user)
        coupon.starts_at=None;coupon.allowed_user=None;coupon.save()
        for line in [self.line('0'),self.line('100','donation')]:
            with self.assertRaises(ValidationError):calculate_discount(coupon.code,[line])
    def test_invalid_configuration_and_tiny_remaining_payment(self):
        coupon=self.coupon();coupon.value=101
        with self.assertRaises(ModelValidationError):coupon.full_clean()
        coupon.value=99;coupon.save()
        with self.assertRaises(ValidationError):calculate_discount(coupon.code,[self.line('30')])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class BookingDiscountTests(TestCase):
    def setUp(self):
        self.student,self.teacher_user,self.teacher,self.slot,self.config,self.api=fixture()
        self.coupon=DiscountCode.objects.create(code='CLASS20',name='Classes',value=20)
        self.api.post('/api/academy/cart/',{'slot_id':str(self.slot.pk)},format='json')
    def pay(self,code='CLASS20',request_id=None):
        return self.api.post('/api/academy/checkout/',{'request_id':request_id or str(uuid.uuid4()),'timezone':'Asia/Tehran','discount_code':code},format='json')
    def test_preview_does_not_reserve_and_checkout_ignores_browser_amount(self):
        quote=self.api.post('/api/academy/cart/quote/',{'discount_code':'class20','total':'1'},format='json')
        self.assertEqual(quote.status_code,200,quote.data);self.assertEqual(quote.data['total'],'20.00');self.assertFalse(Order.objects.exists())
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            response=self.pay();self.assertEqual(response.status_code,200,response.data)
            params=gateway.return_value.v1.checkout.sessions.create.call_args.args[0]
            self.assertEqual(params['line_items'][0]['price_data']['unit_amount'],2000)
        order=Order.objects.get();booking=Booking.objects.get()
        self.assertEqual((order.subtotal,order.discount_amount,order.amount),(25,5,20))
        self.assertEqual((booking.original_amount,booking.amount),(25,20))
    def test_free_discount_confirms_without_stripe_and_excludes_trials(self):
        self.coupon.value=100;self.coupon.save()
        with patch('academy.views.client') as gateway:
            response=self.pay();self.assertEqual(response.status_code,200,response.data);gateway.assert_not_called()
        self.assertEqual(Order.objects.get().mode,'free');self.assertEqual(Booking.objects.get().status,'confirmed')
    def test_retries_keep_snapshot_and_cannot_change_code(self):
        request_id=str(uuid.uuid4())
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            first=self.pay(request_id=request_id);self.assertEqual(first.status_code,200,first.data)
        self.coupon.value=50;self.coupon.active=False;self.coupon.save()
        with patch('academy.views.client') as gateway:
            self.assertEqual(self.pay(request_id=request_id).status_code,200);gateway.assert_not_called()
        self.assertEqual(Order.objects.get().amount,20)
        self.assertEqual(self.pay(code='',request_id=request_id).status_code,409)
    def test_invalid_discount_creates_no_hold_and_new_checkout_revalidates(self):
        self.assertEqual(self.pay(code='missing').status_code,400)
        self.assertFalse(Order.objects.exists());self.assertFalse(Booking.objects.exists())
        self.assertEqual(self.api.post('/api/academy/cart/quote/',{'discount_code':self.coupon.code},format='json').status_code,200)
        self.coupon.active=False;self.coupon.save()
        self.assertEqual(self.pay().status_code,400);self.assertFalse(Order.objects.exists())
    def test_signed_webhook_requires_discounted_total(self):
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            self.assertEqual(self.pay().status_code,200)
        from academy.tests import AcademyTests
        sender=AcademyTests();sender.config=self.config
        order=Order.objects.get()
        self.assertEqual(sender.send_event(sender.event(order,amount=2500)).status_code,400)
        self.assertEqual(sender.send_event(sender.event(order,amount=2000)).status_code,200)
        order.refresh_from_db();self.assertEqual(order.status,'paid')


class ProductDiscountTests(TestCase):
    def setUp(self):
        self.student,_,_,_,self.config,self.api=fixture()
        self.config.other_payments_enabled=True;self.config.save()
        self.item=PaymentItem.objects.create(slug='workshop',title='Workshop',amount=100)
        self.coupon=DiscountCode.objects.create(code='ITEM10',name='Workshop',discount_type='fixed',value=10,all_products=False)
        self.coupon.payment_items.add(self.item)
        self.data={'request_id':str(uuid.uuid4()),'purpose':'other','reference':'workshop','discount_code':'ITEM10','first_name':'Example','email':'learner@example.com'}
    def test_product_quote_and_checkout_are_authoritative(self):
        quote=APIClient().post('/api/payments/discount/',self.data,format='json')
        self.assertEqual(quote.status_code,200,quote.data);self.assertEqual(quote.data['total'],'90.00')
        with patch('catalog.payments.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.return_value=SimpleNamespace(id='cs_fixture',url='https://checkout.stripe.com/c/pay/fixture',expires_at=int(timezone.now().timestamp())+3600,livemode=False)
            response=APIClient().post('/api/payments/checkout/',self.data,format='json');self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(gateway.return_value.v1.checkout.sessions.create.call_args.args[0]['line_items'][0]['price_data']['unit_amount'],9000)
        order=PaymentOrder.objects.get();self.assertEqual((order.subtotal,order.discount_amount,order.amount),(100,10,90))
    def test_personal_product_code_requires_authenticated_account_not_claimed_email(self):
        self.coupon.allowed_user=self.student;self.coupon.save()
        self.assertEqual(APIClient().post('/api/payments/checkout/',self.data,format='json').status_code,400)
        self.assertFalse(PaymentOrder.objects.exists())
        self.assertEqual(self.api.post('/api/payments/discount/',self.data,format='json').status_code,200)
    def test_fully_discounted_product_no_stripe_call(self):
        self.coupon.value=100;self.coupon.save()
        with patch('catalog.payments.client') as gateway:
            response=APIClient().post('/api/payments/checkout/',self.data,format='json')
            self.assertEqual(response.status_code,200,response.data);self.assertEqual(response.data['status'],'paid');gateway.assert_not_called()
        self.assertEqual(PaymentOrder.objects.get().mode,'free')
