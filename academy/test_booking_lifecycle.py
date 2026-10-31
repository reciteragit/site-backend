import base64,json,time,uuid
from datetime import timedelta
from unittest.mock import patch
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes
from .tests import fixture
from .models import Booking,Order,BookingNotice,CancellationRequest
from .booking_notices import queue_reminders,flush_notices,deliver_notice
from .notifications import calendar
from .services import available_queryset
from .workflow_auth import workflow_authorized,WORKFLOW,AUDIENCE


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',DEFAULT_FROM_EMAIL='info@recitera.com')
class BookingLifecycleTests(TestCase):
    def setUp(self):
        self.student,self.teacher_user,self.teacher,self.slot,_,self.api=fixture()
        self.order=Order.objects.create(request_id=uuid.uuid4(),user=self.student,email=self.student.email,amount=25,mode='test',status='paid',expires_at=timezone.now()+timedelta(hours=1),paid_at=timezone.now())
        self.booking=Booking.objects.create(order=self.order,slot=self.slot,student=self.student,student_timezone='Asia/Tehran',teacher_timezone='America/Toronto',teacher_name='Teacher',amount=25,meeting_url='https://meet.google.com/abc-defg-hij',status='confirmed')
        self.teacher_api=APIClient();self.teacher_api.force_authenticate(self.teacher_user)
        self.request_url=f'/api/academy/bookings/{self.booking.pk}/cancellation/'
        self.decision_url=f'/api/academy/teacher/bookings/{self.booking.pk}/cancellation/'

    def test_two_reminders_for_both_people_with_retry_and_recipient_timezones(self):
        queue_reminders(self.booking);queue_reminders(self.booking)
        self.assertEqual(BookingNotice.objects.count(),4)
        due=self.slot.starts_at-timedelta(hours=24)
        with patch('academy.booking_notices.timezone.now',return_value=due+timedelta(minutes=1)):
            self.assertEqual(flush_notices(),2)
            self.assertEqual(flush_notices(),0)
        self.assertEqual({msg.to[0] for msg in mail.outbox},{self.student.email,self.teacher_user.email})
        self.assertTrue(any('Asia/Tehran' in msg.body for msg in mail.outbox))
        self.assertTrue(any('America/Toronto' in msg.body for msg in mail.outbox))
        due=self.slot.starts_at-timedelta(minutes=30)
        with patch('academy.booking_notices.timezone.now',return_value=due+timedelta(minutes=1)):
            self.assertEqual(flush_notices(),2)
        self.assertEqual(len(mail.outbox),4)
        self.assertTrue(all(msg.attachments for msg in mail.outbox))

    def test_late_booking_skips_24h_reminder_and_failed_send_retries(self):
        self.order.paid_at=self.slot.starts_at-timedelta(hours=2);self.order.save()
        with patch('academy.booking_notices.timezone.now',return_value=self.order.paid_at):queue_reminders(self.booking)
        self.assertEqual(BookingNotice.objects.count(),2)
        notice=BookingNotice.objects.first()
        with patch('academy.booking_notices.timezone.now',return_value=notice.due_at+timedelta(seconds=1)):
            with patch('academy.booking_notices.EmailMessage.send',side_effect=RuntimeError('outage')):
                self.assertFalse(deliver_notice(notice.pk))
            notice.refresh_from_db();self.assertIsNone(notice.sent_at)
            self.assertTrue(deliver_notice(notice.pk))
            self.assertFalse(deliver_notice(notice.pk))

    def test_teacher_approval_required_then_slot_reopens_and_reminders_stop(self):
        queue_reminders(self.booking)
        response=self.api.post(self.request_url,{'reason':'Schedule change'},format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.api.post(self.request_url,{},format='json').status_code,200)
        self.assertEqual(CancellationRequest.objects.count(),1)
        self.booking.refresh_from_db();self.assertEqual(self.booking.status,'confirmed')
        self.assertFalse(available_queryset().filter(pk=self.slot.pk).exists())
        self.assertEqual(self.api.post(self.decision_url,{'decision':'approve'},format='json').status_code,404)
        self.assertEqual(flush_notices(),1)
        self.assertEqual(mail.outbox[0].to,[self.teacher_user.email])
        response=self.teacher_api.post(self.decision_url,{'decision':'approve'},format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.teacher_api.post(self.decision_url,{'decision':'approve'},format='json').status_code,200)
        self.booking.refresh_from_db();self.assertEqual(self.booking.status,'cancelled')
        self.assertTrue(available_queryset().filter(pk=self.slot.pk).exists())
        self.assertEqual(flush_notices(),2)
        self.assertIn('STATUS:CANCELLED',calendar(self.booking))
        self.assertEqual(self.api.get(f'/api/academy/bookings/{self.booking.pk}/calendar/').status_code,200)
        due=self.slot.starts_at-timedelta(minutes=29)
        with patch('academy.booking_notices.timezone.now',return_value=due):self.assertEqual(flush_notices(),0)
        self.order.refresh_from_db();self.assertEqual(self.order.status,'paid')

    def test_deadline_privacy_decline_and_calendar_links(self):
        other=get_user_model().objects.create_user('unrelated-student');client=APIClient();client.force_authenticate(other)
        self.assertEqual(client.post(self.request_url,{},format='json').status_code,404)
        with patch('academy.cancellations.timezone.now',return_value=self.slot.starts_at-timedelta(hours=24)+timedelta(seconds=1)):
            self.assertEqual(self.api.post(self.request_url,{},format='json').status_code,403)
        with patch('academy.cancellations.timezone.now',return_value=self.slot.starts_at-timedelta(hours=24)):
            self.assertEqual(self.api.post(self.request_url,{},format='json').status_code,200)
        self.assertEqual(self.teacher_api.post(self.decision_url,{'decision':'decline'},format='json').status_code,200)
        self.booking.refresh_from_db();self.assertEqual(self.booking.status,'confirmed')
        self.assertEqual(self.teacher_api.post(self.decision_url,{'decision':'approve'},format='json').status_code,403)
        data=self.api.get('/api/academy/bookings/').data['bookings'][0]
        self.assertTrue(data['calendar_links']['google'].startswith('https://calendar.google.com/'))
        self.assertTrue(data['calendar_links']['outlook'].startswith('https://outlook.live.com/'))
        self.assertFalse(data['can_request_cancellation'])
        self.assertEqual(client.get(f'/api/academy/bookings/{self.booking.pk}/calendar/').status_code,404)


class WorkflowAuthenticationTests(TestCase):
    def test_only_signed_trusted_workflow_can_trigger_mail(self):
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        def b64(value):return base64.urlsafe_b64encode(value).rstrip(b'=').decode()
        def number(value):return b64(value.to_bytes((value.bit_length()+7)//8,'big'))
        public=private.public_key().public_numbers()
        cache.set('recitera-github-oidc-jwks',[{'kid':'local','kty':'RSA','e':number(public.e),'n':number(public.n)}],300)
        claims={'iss':'https://token.actions.githubusercontent.com','aud':AUDIENCE,'repository':'reciteragit/site-backend','ref':'refs/heads/main','workflow_ref':WORKFLOW,'event_name':'schedule','sub':'repo:reciteragit/site-backend:ref:refs/heads/main','exp':time.time()+300,'iat':time.time()}
        def token(changes=None):
            body=b64(json.dumps({'alg':'RS256','kid':'local'}).encode())+'.'+b64(json.dumps({**claims,**(changes or {})}).encode())
            return body+'.'+b64(private.sign(body.encode(),padding.PKCS1v15(),hashes.SHA256()))
        self.assertTrue(workflow_authorized(token()))
        for changes in [{'repository':'attacker/repo'},{'ref':'refs/heads/other'},{'event_name':'pull_request'},{'workflow_ref':'wrong'},{'job_workflow_ref':'wrong'},{'exp':time.time()-60},{'aud':'wrong'}]:self.assertFalse(workflow_authorized(token(changes)))
        self.assertFalse(workflow_authorized(token()+'tampered'))
        with patch.dict('os.environ',{'CRON_SECRET':''}):
            self.assertEqual(APIClient().get('/api/academy/internal/send-mail/').status_code,403)
            response=APIClient().get('/api/academy/internal/send-mail/',HTTP_AUTHORIZATION='Bearer '+token())
            self.assertEqual(response.status_code,200)
