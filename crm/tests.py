import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail,signing
from django.test import TestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from academy.tests import fixture
from academy.models import Order,Booking,Slot,BookingNotice
from academy.booking_notices import queue_reminders
from catalog.models import ScholarshipApplication
from catalog.payment_models import Donor,PaymentOrder
from .models import Lead,TrialRequest,TrialRecord,Communication,LeadEvent
from .services import sync_sources,sync_conversion
from .communications import deliver


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',DEFAULT_FROM_EMAIL='info@recitera.com')
class CRMTests(TestCase):
    def tearDown(self):
        from django.core.cache import cache
        cache.clear()
    def setUp(self):
        self.user,self.teacher_user,self.teacher,self.slot,self.config,self.api=fixture()
        self.slot.kind='trial';self.slot.save()
        self.teacher_api=APIClient();self.teacher_api.force_authenticate(self.teacher_user)
        self.order=Order.objects.create(user=self.user,email=self.user.email,request_id=uuid.uuid4(),amount=0,mode='free',status='paid',paid_at=timezone.now(),expires_at=timezone.now()+timedelta(hours=1))
    def trial(self):
        return Booking.objects.create(order=self.order,slot=self.slot,student=self.user,student_timezone='Asia/Tehran',teacher_timezone='America/Toronto',teacher_name='Teacher',amount=0,meeting_url='https://lms.recitera.com',status='confirmed')
    def payment(self,mode='live'):
        donor,_=Donor.objects.get_or_create(email=self.user.email,defaults={'first_name':'Learner'})
        return PaymentOrder.objects.create(donor=donor,buyer=self.user,first_name='Learner',request_id=uuid.uuid4(),purpose='course',reference='course',title='Quran course',amount=5,subtotal=5,mode=mode,status='paid',paid_at=timezone.now())
    def test_requests_scholarships_and_bookings_are_captured_idempotently(self):
        key=uuid.uuid4();payload={'request_id':str(key),'name':'Parent','email':'parent@example.com','timezone':'Europe/Paris','language':'English','campaign':'autumn','goals':'Tajweed'}
        guest=APIClient()
        self.assertEqual(guest.post('/api/forms/trial/',payload,format='json').status_code,201)
        self.assertEqual(guest.post('/api/forms/trial/',payload,format='json').status_code,201)
        self.assertEqual(TrialRequest.objects.count(),1);self.assertEqual(Lead.objects.count(),1)
        self.assertIsNone(Lead.objects.get().user_id)
        self.assertEqual(Communication.objects.filter(kind='trial_received').count(),1)
        app=ScholarshipApplication.objects.create(name='Parent',email='parent@example.com',whatsapp='+123456789')
        self.assertEqual(Lead.objects.get(scholarship=app).source,'scholarship')
        booking=self.trial();sync_sources();sync_sources()
        self.assertEqual(Lead.objects.count(),3);self.assertEqual(TrialRecord.objects.count(),1)
        self.assertEqual(booking.crm_trial.lead.stage,'trial_booked')
        self.assertEqual(Communication.objects.filter(kind='trial_followup').count(),1)
    def test_test_payments_do_not_convert_and_real_payments_do_not_regress(self):
        booking=self.trial();lead=booking.crm_trial.lead
        self.payment('test');lead.refresh_from_db();self.assertEqual(lead.stage,'trial_booked')
        self.payment();lead.refresh_from_db();self.assertEqual(lead.stage,'converted')
        booking.save();lead.refresh_from_db();self.assertEqual(lead.stage,'converted')
        lead.stage='dropped';lead.drop_reason='No longer interested';lead.save()
        sync_conversion(self.user.pk);lead.refresh_from_db();self.assertEqual(lead.stage,'dropped')
    def test_email_verified_claim_merges_enquiry_and_booking_without_guessing(self):
        enquiry=TrialRequest.objects.create(name='Parent',email=self.user.email,timezone='UTC',campaign='autumn',language='Persian')
        original=Lead.objects.get(trial_request=enquiry)
        booking=self.trial();canonical=booking.crm_trial.lead
        token=signing.dumps({'request_id':str(enquiry.request_id)},salt='recitera-crm-trial-claim')
        other=get_user_model().objects.create_user('wrong-email',email='other@example.com');guest=APIClient();guest.force_authenticate(other)
        self.assertEqual(guest.post('/api/academy/crm/claim-trial/',{'token':token},format='json').status_code,403)
        for _ in range(2):self.assertEqual(self.api.post('/api/academy/crm/claim-trial/',{'token':token},format='json').status_code,200)
        original.refresh_from_db();canonical.refresh_from_db()
        self.assertEqual(original.merged_into_id,canonical.pk)
        self.assertEqual(canonical.campaign,'autumn');self.assertEqual(canonical.language,'Persian')
        self.assertEqual(Lead.objects.filter(merged_into__isnull=True).count(),1)
        self.assertEqual(self.api.post('/api/academy/crm/claim-trial/',{'token':'bad'},format='json').status_code,400)
    def test_reminders_include_trial_link_5_minutes_before_for_both_people(self):
        booking=self.trial();queue_reminders(booking)
        self.assertEqual(BookingNotice.objects.filter(kind='reminder_5m').count(),2)
        due=booking.slot.starts_at-timedelta(minutes=5)
        from academy.booking_notices import flush_notices
        with patch('academy.booking_notices.timezone.now',return_value=due+timedelta(seconds=5)):
            self.assertEqual(flush_notices(),2)
        self.assertTrue(all('https://lms.recitera.com' in msg.body for msg in mail.outbox))
    def test_followup_retry_and_suppression_after_conversion_or_cancellation(self):
        booking=self.trial();item=Communication.objects.get(booking=booking)
        self.assertFalse(deliver(item.pk))
        with patch('crm.communications.timezone.now',return_value=item.due_at+timedelta(seconds=1)):
            with patch('crm.communications.EmailMessage.send',side_effect=RuntimeError('outage')):self.assertFalse(deliver(item.pk))
            self.assertTrue(deliver(item.pk));self.assertFalse(deliver(item.pk))
        self.assertEqual(len(mail.outbox),1);self.assertIn('How did your scheduled',mail.outbox[0].subject)
        self.assertIn('trial-feedback-',mail.outbox[0].body)
        item.sent_at=None;item.save()
        self.payment()
        with patch('crm.communications.timezone.now',return_value=item.due_at+timedelta(seconds=1)):self.assertFalse(deliver(item.pk))
        item.refresh_from_db();self.assertIsNotNone(item.suppressed_at)
        booking.status='cancelled';booking.save();booking.crm_trial.refresh_from_db();self.assertEqual(booking.crm_trial.outcome,'cancelled')
    def test_feedback_and_attendance_require_correct_account_and_finished_trial(self):
        booking=self.trial();url=f'/api/academy/bookings/{booking.pk}/feedback/';teacher_url=f'/api/academy/teacher/bookings/{booking.pk}/trial-report/'
        feedback={'rating':5,'feedback':'Helpful','interest':'continue'}
        self.assertEqual(self.api.post(url,feedback,format='json').status_code,403)
        with patch('crm.views.timezone.now',return_value=self.slot.ends_at+timedelta(minutes=1)):
            self.assertEqual(self.teacher_api.post(url,feedback,format='json').status_code,404)
            self.assertEqual(self.api.post(teacher_url,{'outcome':'attended'},format='json').status_code,404)
            self.assertEqual(self.teacher_api.post(teacher_url,{'outcome':'attended','notes':'Good start','assessed_level':'Beginner'},format='json').status_code,200)
            self.assertEqual(self.api.post(url,feedback,format='json').status_code,200)
        record=TrialRecord.objects.get();record.lead.refresh_from_db();self.assertEqual(record.lead.stage,'trial_completed')
        self.assertEqual(record.feedback_rating,5);self.assertEqual(record.teacher_notes,'Good start')
        feedback['interest']='not_continue';feedback['feedback']='Schedule not suitable'
        with patch('crm.views.timezone.now',return_value=self.slot.ends_at+timedelta(minutes=2)):self.api.post(url,feedback,format='json')
        record.lead.refresh_from_db();self.assertTrue(record.lead.do_not_contact);self.assertEqual(record.lead.stage,'dropped')
    def test_existing_sources_backfill_and_old_trials_do_not_send_stale_followup(self):
        booking=self.trial();Communication.objects.all().delete();TrialRecord.objects.all().delete()
        Slot.objects.filter(pk=self.slot.pk).update(starts_at=timezone.now()-timedelta(days=10),ends_at=timezone.now()-timedelta(days=10)+timedelta(minutes=15))
        sync_sources();self.assertEqual(TrialRecord.objects.count(),1)
        self.assertIsNotNone(Communication.objects.get().suppressed_at)
    def test_admin_pipeline_permission_and_filtered_conversion(self):
        self.trial();admin=get_user_model().objects.create_superuser('crm-admin','admin@example.com','local-test-password');self.client.force_login(admin)
        response=self.client.get('/admin/crm/lead/');self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['crm_metrics']['trial_contacts'],1)
        self.assertEqual(response.context['crm_metrics']['converted'],0)
        self.payment();response=self.client.get('/admin/crm/lead/',{'trial_teacher':self.teacher.teacher_id})
        self.assertEqual(response.context['crm_metrics']['converted'],1)
        self.client.force_login(self.user);self.assertEqual(self.client.get('/admin/crm/lead/').status_code,302)

    def test_late_payment_reconciliation_and_stable_email_claim_token(self):
        booking=self.trial();lead=booking.crm_trial.lead
        paid=self.payment('test')
        PaymentOrder.objects.filter(pk=paid.pk).update(mode='live')
        lead.refresh_from_db();self.assertEqual(lead.stage,'trial_booked')
        sync_sources();lead.refresh_from_db();self.assertEqual(lead.stage,'converted')
        enquiry=TrialRequest.objects.create(name='Parent',email=self.user.email,timezone='UTC')
        from .services import claim_token
        first=claim_token(enquiry)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+300):self.assertEqual(claim_token(enquiry),first)
        self.assertEqual(signing.loads(first,salt='recitera-crm-trial-claim',max_age=604800)['request_id'],str(enquiry.request_id))
        from academy.google_auth import safe_next
        from urllib.parse import urlencode
        target='/account?'+urlencode({'trial_claim':first})
        self.assertEqual(safe_next(target),target)
        self.assertEqual(safe_next('//example.org/account'),'/account')
