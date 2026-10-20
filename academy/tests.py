import hashlib
import hmac
import json
import threading
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from catalog.models import Teacher
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import encrypt
from .models import Profile, TeachingProfile, Slot, CartItem, Booking, Order, EmailDelivery, AccessToken
from .authentication import issue_token
from .services import expire_holds, valid_meeting
from .timezones import local_time
from .notifications import deliver, calendar

User=get_user_model()


def fixture():
    cache.clear()
    student=User.objects.create_user(username='learner@example.com',email='learner@example.com',password='strong-example-PASS9')
    Profile.objects.create(user=student,timezone='Asia/Tehran')
    teacher_user=User.objects.create_user(username='teacher@example.com',email='teacher@example.com',password='strong-example-PASS9')
    teacher=Teacher.objects.create(slug='test-teacher',name='Test teacher',experience='5 years',languages=['English'],image='/assets/amin.jpg',profile_url='',price=25,currency='CAD')
    teaching=TeachingProfile.objects.create(user=teacher_user,teacher=teacher,approved=True,timezone='America/Toronto',meeting_provider='meet',meeting_url='https://meet.google.com/abc-defg-hij')
    start=(timezone.now()+timedelta(days=3)).replace(second=0,microsecond=0)
    slot=Slot.objects.create(teacher=teaching,starts_at=start,ends_at=start+timedelta(minutes=30))
    config=StripeSettings.objects.create(enabled=True,mode='test',lessons_enabled=True,test_secret_ciphertext=encrypt('sk_test_fixture'),test_webhook_ciphertext=encrypt('whsec_fixture'))
    client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(student))
    return student,teacher_user,teaching,slot,config,client


def stripe_session(params,options):
    return SimpleNamespace(id='cs_'+params['metadata']['academy_order_id'],url='https://checkout.stripe.com/c/pay/test',livemode=False,expires_at=params['expires_at'])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',DEFAULT_FROM_EMAIL='info@recitera.com')
class AcademyTests(TestCase):
    def setUp(self):self.student,self.teacher_user,self.teacher,self.slot,self.config,self.api=fixture()
    def teacher_client(self):
        c=APIClient();c.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(self.teacher_user));return c
    def reserve(self):
        self.assertEqual(self.api.post('/api/academy/cart/',{'slot_id':str(self.slot.id)},format='json').status_code,200)
        with patch('academy.views.client') as factory:
            factory.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            r=self.api.post('/api/academy/checkout/',{'request_id':str(uuid.uuid4()),'timezone':'Asia/Tehran'},format='json')
        self.assertEqual(r.status_code,200,r.data)
        return Order.objects.get(pk=r.data['id'])
    def event(self,order,event_type='checkout.session.completed',event_id=None,amount=None):
        return {'id':event_id or 'evt_'+uuid.uuid4().hex,'type':event_type,'livemode':False,'data':{'object':{'id':order.stripe_session_id,'client_reference_id':str(order.pk),'metadata':{'academy_order_id':str(order.pk)},'amount_total':int(order.amount*100) if amount is None else amount,'currency':'cad','payment_status':'paid' if event_type=='checkout.session.completed' else 'unpaid'}}}
    def send_event(self,event,secret='whsec_fixture'):
        raw=json.dumps(event).encode();stamp=int(time.time());digest=hmac.new(secret.encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return APIClient().post('/api/payments/stripe/webhook/',raw,content_type='application/json',HTTP_STRIPE_SIGNATURE=f't={stamp},v1={digest}')
    def test_registration_authentication_and_session_revocation(self):
        c=APIClient()
        self.assertEqual(c.get('/api/academy/me/').status_code,401)
        data={'email':'NEW@example.com','password':'Complex-registration-99!','first_name':'New','timezone':'Europe/Berlin'}
        r=c.post('/api/academy/auth/register/',data,format='json');self.assertEqual(r.status_code,201,r.data)
        raw=r.data['token'];self.assertFalse(AccessToken.objects.filter(digest=raw).exists())
        c.credentials(HTTP_AUTHORIZATION='Bearer '+raw)
        self.assertEqual(c.get('/api/academy/me/').data['timezone'],'Europe/Berlin')
        self.assertEqual(c.post('/api/academy/auth/logout/',{},format='json').status_code,200)
        self.assertEqual(c.get('/api/academy/me/').status_code,401)
        self.assertEqual(APIClient().post('/api/academy/auth/login/',{'email':data['email'],'password':data['password']},format='json').status_code,200)
    def test_password_change_revokes_all_sessions(self):
        r=self.api.post('/api/academy/auth/password/',{'current_password':'strong-example-PASS9','password':'Replacement-password-9!'},format='json')
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.api.get('/api/academy/me/').status_code,401)
    def test_new_teacher_cannot_self_approve_or_change_classroom(self):
        body={'name':'New teacher','experience':'2 years','languages':['Arabic'],'image':'/assets/amin.jpg','price':'30.00','timezone':'Asia/Tehran','approved':True,'meeting_url':'https://meet.google.com/fake'}
        r=self.api.post('/api/academy/teacher/profile/',body,format='json');self.assertEqual(r.status_code,200,r.data)
        p=TeachingProfile.objects.get(user=self.student)
        self.assertFalse(p.approved);self.assertFalse(p.teacher.published);self.assertEqual(p.meeting_url,'https://lms.recitera.com/');self.assertEqual(p.meeting_provider,'lms')
    def test_only_allowed_meeting_providers_and_hosts(self):
        for provider,url in [('zoom','https://us02web.zoom.us/j/123'),('meet','https://meet.google.com/abc-defg-hij'),('lms','https://lms.recitera.com/room/123'),('lms','https://lms.recitera.com/')]:self.assertTrue(valid_meeting(provider,url))
        for url in ['http://meet.google.com/a','https://meet.google.com.evil.test/a','https://user:pass@meet.google.com/a','https://meet.google.com:999/a','javascript:alert(1)','https://meet.google.com']:
            self.assertFalse(valid_meeting('meet',url))
    def test_dst_nonexistent_and_ambiguous_local_times_rejected(self):
        for value in ['2027-03-14T02:30','2026-11-01T01:30']:
            with self.assertRaises(ValidationError):local_time(value,'America/Toronto')
        self.assertEqual(local_time('2027-01-15T10:00','America/Toronto').isoformat(),'2027-01-15T15:00:00+00:00')
        self.assertEqual(local_time('2027-07-15T10:00','America/Toronto').isoformat(),'2027-07-15T14:00:00+00:00')
        self.assertEqual(local_time('2027-07-15T17:30','Asia/Tehran').isoformat(),'2027-07-15T14:00:00+00:00')
    def test_teacher_availability_rejects_overlap_and_preserves_utc_on_zone_change(self):
        c=self.teacher_client();start=self.slot.starts_at.astimezone(__import__('zoneinfo').ZoneInfo('America/Toronto')).replace(tzinfo=None).isoformat()
        r=c.post('/api/academy/teacher/slots/',{'starts_local':start,'duration_minutes':30},format='json');self.assertEqual(r.status_code,409)
        self.teacher.timezone='Europe/London';self.teacher.save();self.slot.refresh_from_db()
        self.assertEqual(self.slot.starts_at,self.slot.starts_at.astimezone(__import__('datetime').timezone.utc))
    def test_cart_is_not_a_hold_and_prices_are_server_authoritative(self):
        self.api.post('/api/academy/cart/',{'slot_id':str(self.slot.pk),'price':'1'},format='json')
        self.assertEqual(len(APIClient().get('/api/academy/teachers/test-teacher/slots/').data),1)
        order=self.reserve();self.assertEqual(order.amount,Decimal('25'))
        self.assertEqual(len(APIClient().get('/api/academy/teachers/test-teacher/slots/').data),0)
        self.assertEqual(Booking.objects.get().status,'held')
        self.assertFalse(EmailDelivery.objects.exists())
    def test_stripe_connection_failure_retains_idempotent_retryable_reservation(self):
        self.api.post('/api/academy/cart/',{'slot_id':str(self.slot.pk)},format='json')
        request_id=str(uuid.uuid4())
        data={'request_id':request_id,'timezone':'Asia/Tehran'}
        import stripe
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe.APIConnectionError('test connection failure')
            self.assertEqual(self.api.post('/api/academy/checkout/',data,format='json').status_code,503)
        self.assertEqual(Order.objects.count(),1);self.assertEqual(Booking.objects.filter(status='held').count(),1)
        self.assertEqual(self.api.get('/api/academy/bookings/').data['orders'][0]['request_id'],request_id)
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            self.assertEqual(self.api.post('/api/academy/checkout/',data,format='json').status_code,200)
        self.assertEqual(Order.objects.count(),1);self.assertEqual(Booking.objects.count(),1)

    def test_idempotent_checkout_and_second_customer_rejected(self):
        order=self.reserve()
        with patch('academy.views.client') as stripe_factory:
            result=self.api.post('/api/academy/checkout/',{'request_id':str(order.request_id),'timezone':'Asia/Tehran'},format='json')
            self.assertEqual(result.status_code,200);stripe_factory.assert_not_called()
        self.assertEqual(Booking.objects.count(),1)
        other=User.objects.create_user('other@example.com',email='other@example.com');c=APIClient();c.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(other))
        CartItem.objects.create(user=other,slot=self.slot)
        result=c.post('/api/academy/checkout/',{'request_id':str(uuid.uuid4()),'timezone':'UTC'},format='json')
        self.assertEqual(result.status_code,409)
    def test_payment_confirmation_is_signed_idempotent_and_emails_private_class_details(self):
        order=self.reserve();event=self.event(order)
        self.assertEqual(self.send_event(event,'invalid-secret').status_code,400)
        self.assertEqual(self.send_event(self.event(order,amount=1)).status_code,400)
        self.assertEqual(Booking.objects.get().status,'held')
        self.assertEqual(self.send_event(event).status_code,200)
        self.assertEqual(self.send_event(event).status_code,200)
        order.refresh_from_db();booking=Booking.objects.get();self.assertEqual(order.status,'paid');self.assertEqual(booking.status,'confirmed')
        self.assertEqual(len(mail.outbox),2)
        student_mail=next(m for m in mail.outbox if m.to==[self.student.email])
        self.assertIn('Asia/Tehran',student_mail.body);self.assertIn(self.teacher.meeting_url,student_mail.body);self.assertIn('[TEST BOOKING]',student_mail.subject)
        self.assertEqual(len(student_mail.attachments),1)
        self.assertFalse(CartItem.objects.filter(user=self.student).exists())
        self.assertNotIn('meeting_url',APIClient().get('/api/academy/teachers/test-teacher/').data)
        data=self.api.get('/api/academy/bookings/').data
        self.assertEqual(data['bookings'][0]['meeting_url'],self.teacher.meeting_url)
        self.assertNotIn(self.student.email,json.dumps(APIClient().get('/api/academy/teachers/test-teacher/slots/').data))
    def test_reserved_slot_cannot_be_deleted_and_calendar_is_private(self):
        order=self.reserve();c=self.teacher_client()
        self.assertEqual(c.delete('/api/academy/teacher/slots/',{'slot_id':str(self.slot.pk)},format='json').status_code,409)
        b=Booking.objects.get();url=f'/api/academy/bookings/{b.pk}/calendar/'
        self.assertEqual(self.api.get(url).status_code,404)
        self.send_event(self.event(order))
        self.assertEqual(self.api.get(url).status_code,200)
        self.assertEqual(APIClient().get(url).status_code,401)
        other=User.objects.create_user('other2@example.com',email='other2@example.com');other_client=APIClient();other_client.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(other))
        self.assertEqual(other_client.get(url).status_code,404)
        self.assertIn('DTSTART:',self.api.get(url).content.decode())
    def test_expired_hold_returns_availability_and_late_payment_conflict_is_reviewed(self):
        order=self.reserve();Order.objects.filter(pk=order.pk).update(expires_at=timezone.now()-timedelta(seconds=1));expire_holds()
        self.assertEqual(len(APIClient().get('/api/academy/teachers/test-teacher/slots/').data),1)
        other=User.objects.create_user('second@example.com',email='second@example.com')
        second=Order.objects.create(request_id=uuid.uuid4(),user=other,email=other.email,amount=25,mode='test',expires_at=timezone.now()+timedelta(minutes=30))
        Booking.objects.create(order=second,slot=self.slot,student=other,student_timezone='UTC',teacher_timezone='UTC',teacher_name='Test teacher',amount=25,meeting_url=self.teacher.meeting_url)
        self.assertEqual(self.send_event(self.event(order)).status_code,200)
        order.refresh_from_db();self.assertEqual(order.status,'payment_review');self.assertEqual(Booking.objects.filter(slot=self.slot,status='confirmed').count(),0)
        self.assertFalse(EmailDelivery.objects.exists())
    def test_failed_payment_releases_slot_but_expiry_never_reverts_paid(self):
        order=self.reserve();self.send_event(self.event(order,event_type='checkout.session.async_payment_failed'))
        self.assertEqual(len(APIClient().get('/api/academy/teachers/test-teacher/slots/').data),1)
        self.send_event(self.event(order));self.send_event(self.event(order,event_type='checkout.session.expired'))
        order.refresh_from_db();self.assertEqual(order.status,'paid');self.assertEqual(Booking.objects.get().status,'confirmed')
    def test_smtp_failure_stays_retryable_without_rebooking_or_duplicate_emails(self):
        order=self.reserve()
        with patch('academy.notifications.EmailMessage.send',side_effect=OSError('offline')):self.send_event(self.event(order))
        self.assertEqual(Booking.objects.get().status,'confirmed');self.assertEqual(EmailDelivery.objects.filter(sent_at__isnull=True).count(),2)
        delivery=EmailDelivery.objects.first();self.assertTrue(deliver(delivery.pk));self.assertFalse(deliver(delivery.pk))
        self.assertEqual(len(mail.outbox),1)
    def test_class_checkout_closed_when_not_configured_and_legacy_payment_rejected(self):
        self.config.lessons_enabled=False;self.config.save()
        self.api.post('/api/academy/cart/',{'slot_id':str(self.slot.pk)},format='json')
        r=self.api.post('/api/academy/checkout/',{'request_id':str(uuid.uuid4()),'timezone':'UTC'},format='json');self.assertEqual(r.status_code,503)
        self.assertFalse(Order.objects.exists())
        self.config.lessons_enabled=True;self.config.save()
        from catalog.payments import price
        with self.assertRaises(ValidationError):price({'purpose':'lesson','reference':'test-teacher'},self.config)
    def test_cron_requires_secret_and_does_not_accept_public_calls(self):
        self.assertEqual(APIClient().get('/api/academy/internal/send-mail/').status_code,403)


@skipUnless(connection.vendor=='postgresql','Row-lock concurrency requires PostgreSQL')
class BookingConcurrencyTests(TransactionTestCase):
    def test_two_parallel_customers_cannot_reserve_same_time(self):
        student,_,teacher,slot,config,first=fixture()
        second_user=User.objects.create_user('race@example.com',email='race@example.com')
        second=APIClient();second.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(second_user))
        for user in [student,second_user]:CartItem.objects.create(user=user,slot=slot)
        barrier=threading.Barrier(2);statuses=[];errors=[]
        def check(client):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                result=client.post('/api/academy/checkout/',{'request_id':str(uuid.uuid4()),'timezone':'UTC'},format='json')
                statuses.append(result.status_code)
            except Exception as e:errors.append(e)
            finally:close_old_connections()
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            threads=[threading.Thread(target=check,args=(c,)) for c in [first,second]]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=20)
        self.assertFalse(errors,errors);self.assertEqual(sorted(statuses),[200,409]);self.assertEqual(Booking.objects.filter(status='held').count(),1)
