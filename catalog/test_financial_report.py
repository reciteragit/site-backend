import csv,io,uuid
from datetime import timedelta,datetime,timezone as utc
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from academy.tests import fixture
from academy.models import Order,Booking,Slot
from learning.models import CoursePurchase
from .models import Course
from .payment_models import Donor,PaymentOrder


class FinancialReportTests(TestCase):
    url='/admin/catalog/paymentorder/report/'
    def setUp(self):
        self.user,_,self.teacher,self.slot,_,_=fixture()
        self.admin=get_user_model().objects.create_superuser('finance-admin','finance@example.com','local-test-password')
        self.client.force_login(self.admin)
        self.donor=Donor.objects.create(email=self.user.email,first_name='Learner')
    def order(self,**kwargs):
        data=dict(user=self.user,email=self.user.email,request_id=uuid.uuid4(),amount=24,subtotal=30,discount_amount=6,currency='CAD',mode='live',status='paid',expires_at=timezone.now()+timedelta(hours=1),paid_at=timezone.now())
        data.update(kwargs);return Order.objects.create(**data)
    def payment(self,**kwargs):
        data=dict(donor=self.donor,buyer=self.user,first_name='Learner',request_id=uuid.uuid4(),purpose='course',reference='quran',title='Quran course',amount=5,subtotal=5,currency='CAD',mode='live',status='paid',paid_at=timezone.now())
        data.update(kwargs);return PaymentOrder.objects.create(**data)
    def get(self,**params):
        response=self.client.get(self.url,{'mode':'all',**params})
        self.assertEqual(response.status_code,200)
        return response
    def totals(self,response):return {(r['currency'],r['mode']):r for r in response.context['totals']}
    def test_combines_sources_but_separates_currencies_modes_and_statuses(self):
        self.order();self.order(status='pending',amount=30,discount_amount=0)
        self.order(mode='test',amount=999)
        self.payment();self.payment(currency='USD',amount=7)
        self.payment(mode='free',amount=0,subtotal=10,discount_amount=10)
        response=self.get();totals=self.totals(response)
        self.assertEqual(totals['CAD','live']['paid'],Decimal('29'))
        self.assertEqual(totals['CAD','live']['pending'],Decimal('30'))
        self.assertEqual(totals['CAD','live']['saved'],Decimal('6'))
        self.assertEqual(totals['CAD','test']['paid'],Decimal('999'))
        self.assertEqual(totals['USD','live']['paid'],Decimal('7'))
        self.assertEqual(response.context['count'],6)
        self.assertIn('private',response['Cache-Control']);self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get(self.url).context['count'],4)
    def test_teacher_course_and_customer_filters_do_not_duplicate_order_totals(self):
        order=self.order()
        for offset in [0,1]:
            slot=Slot.objects.create(teacher=self.teacher,starts_at=self.slot.starts_at+timedelta(hours=offset+1),ends_at=self.slot.ends_at+timedelta(hours=offset+1))
            Booking.objects.create(order=order,slot=slot,student=self.user,teacher_name='Teacher',student_timezone='UTC',teacher_timezone='UTC',meeting_url='https://lms.recitera.com',amount=12,status='confirmed')
        course=Course.objects.create(slug='report-course',title='Course',teacher=self.teacher.teacher,price=5)
        payment=self.payment(purpose='bundle',title='Package')
        CoursePurchase.objects.create(order=payment,course=course)
        self.payment(purpose='donation')
        response=self.get(teacher=self.teacher.teacher_id,q=self.user.email)
        self.assertEqual(response.context['count'],2)
        self.assertEqual(self.totals(response)['CAD','live']['paid'],29)
        self.assertEqual(self.get(course=course.pk).context['count'],1)
        self.assertEqual(self.get(kind='class').context['count'],1)
        self.assertEqual(self.get(kind='donation').context['count'],1)
    def test_local_date_boundaries_and_amount_discount_status_filters(self):
        order=self.order(discount_code='SAVE20')
        Order.objects.filter(pk=order.pk).update(created_at=datetime(2026,10,31,1,tzinfo=utc.utc))
        self.assertEqual(self.get(start='2026-10-30',end='2026-10-30',timezone='America/Los_Angeles').context['count'],1)
        self.assertEqual(self.get(start='2026-10-31',end='2026-10-31',timezone='America/Los_Angeles').context['count'],0)
        self.assertEqual(self.get(minimum='24',maximum='24',discount_code='save20',status='paid').context['count'],1)
        self.assertEqual(self.get(minimum='25').context['count'],0)
        response=self.get(start='2026-11-01',end='2026-10-01')
        self.assertFalse(response.context['form'].is_valid());self.assertIsNone(response.context['page'])
    def test_csv_exports_all_filtered_rows_and_neutralizes_formulas(self):
        self.payment(title='=HYPERLINK("https://example.org")')
        for _ in range(51):self.order()
        response=self.get()
        self.assertEqual(len(response.context['page']),50)
        self.assertEqual(self.totals(response)['CAD','live']['paid'],Decimal('1229'))
        response=self.client.get(self.url,{'mode':'all','format':'csv'})
        rows=list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))))
        self.assertEqual(len(rows),53)
        self.assertTrue(any(row[3].startswith("'=HYPERLINK") for row in rows[1:]))
        response=self.client.get(self.url,{'mode':'all','format':'csv','kind':'course'})
        self.assertEqual(len(list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))))),2)
    def test_requires_both_financial_model_permissions(self):
        self.client.logout();self.assertEqual(self.client.get(self.url).status_code,302)
        self.client.force_login(self.user);self.assertEqual(self.client.get(self.url).status_code,302)
        staff=get_user_model().objects.create_user('finance-staff',is_staff=True)
        self.client.force_login(staff);self.assertEqual(self.client.get(self.url).status_code,403)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='catalog',codename='view_paymentorder'))
        self.assertEqual(self.client.get(self.url).status_code,403)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='academy',codename='view_order'))
        self.assertEqual(self.client.get(self.url).status_code,200)
