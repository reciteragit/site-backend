import io,json,logging,uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from academy.tests import fixture
from academy.models import Order,Booking,CancellationRequest
from catalog.models import ScholarshipApplication,TeacherApplication,VolunteerApplication,NewsletterSubscriber
from catalog.stripe_gateway import encrypt,decrypt
from crm.models import TrialRequest
from .models import TelegramSettings,TelegramMessage
from .outbox import queue
from .sender import deliver,flush,api,TelegramFailure
from .logging import SafeTelegramErrorHandler
from .admin import ConnectionForm

TOKEN='123456:abcdefghijklmnopqrstuvwxyz_ABCDEF'


class TelegramTests(TestCase):
    def setUp(self):
        self.user,_,self.teacher,self.slot,_,_=fixture()
        self.config=TelegramSettings.objects.create(enabled=True,token_ciphertext=encrypt(TOKEN),chat_id='-100123456789')
    def test_forms_and_crm_capture_once_without_contact_details_or_inline_network(self):
        with patch('operations.sender.urlopen') as network:
            enquiry=TrialRequest.objects.create(name='Private Person',email='private@example.com',whatsapp='+1234567890',goals='Private learning notes')
            enquiry.save()
            ScholarshipApplication.objects.create(name='Parent',email='parent@example.com',whatsapp='+123456789',message='Sensitive support notes')
            TeacherApplication.objects.create(full_name='Teacher',email='teacher@example.com',whatsapp='+123456789',preferences='Private profile details')
            VolunteerApplication.objects.create(name='Volunteer',email='volunteer@example.com',whatsapp='+123456789',message='Private details')
            NewsletterSubscriber.objects.create(email='newsletter@example.com')
            network.assert_not_called()
        self.assertEqual(TelegramMessage.objects.filter(category='forms').count(),5)
        self.assertTrue(TelegramMessage.objects.filter(category='crm').exists())
        text=' '.join(TelegramMessage.objects.values_list('text',flat=True))
        for private in ['Private Person','private@example.com','+1234567890','Private learning notes','Sensitive support notes','Private profile details']:self.assertNotIn(private,text)
        self.assertIn('/admin/',text)
        self.config.include_contact_details=True;self.config.save()
        TrialRequest.objects.create(name='Allowed Contact',email='allowed@example.com',goals='Never forward this note')
        text=' '.join(TelegramMessage.objects.values_list('text',flat=True))
        self.assertIn('Allowed Contact',text);self.assertIn('allowed@example.com',text);self.assertNotIn('Never forward this note',text)
    def test_booking_payment_and_cancellation_state_events_are_deduplicated(self):
        order=Order.objects.create(user=self.user,email=self.user.email,request_id=uuid.uuid4(),amount=30,mode='live',status='paid',expires_at=timezone.now()+timedelta(hours=1))
        booking=Booking.objects.create(order=order,slot=self.slot,student=self.user,student_timezone='UTC',teacher_timezone='UTC',teacher_name='Public Teacher',amount=30,meeting_url='https://meet.google.com/private-class-link',status='confirmed')
        booking.save();order.save()
        request=CancellationRequest.objects.create(booking=booking)
        request.status='approved';request.save();request.save()
        self.assertEqual(TelegramMessage.objects.filter(key=f'academy:booking:{booking.pk}:confirmed').count(),1)
        self.assertEqual(TelegramMessage.objects.filter(key=f'academy:order:{order.pk}:paid').count(),1)
        self.assertEqual(TelegramMessage.objects.filter(key=f'academy:cancellationrequest:{request.pk}:approved').count(),1)
        self.assertFalse(TelegramMessage.objects.filter(text__contains='private-class-link').exists())
    def test_disabled_or_failed_queue_does_not_break_business(self):
        self.config.enabled=False;self.config.save()
        TrialRequest.objects.create(name='Contact',email='contact@example.com')
        self.assertEqual(TelegramMessage.objects.count(),0)
        self.config.enabled=True;self.config.save()
        with patch('operations.outbox.TelegramMessage.objects.get_or_create',side_effect=RuntimeError('queue offline')):
            application=ScholarshipApplication.objects.create(name='Contact',email='contact@example.com',whatsapp='+123456789')
        self.assertTrue(ScholarshipApplication.objects.filter(pk=application.pk).exists())
    def test_delivery_retry_rate_limit_and_no_resend(self):
        pk=queue('test:send','forms','Test event')
        with patch('operations.sender.api',side_effect=TelegramFailure('rate_limited',120)):
            self.assertFalse(deliver(pk))
        row=TelegramMessage.objects.get(pk=pk);self.assertEqual(row.last_error,'rate_limited');self.assertIsNone(row.sent_at)
        with patch('operations.sender.api',return_value={'message_id':99}) as send:
            self.assertFalse(deliver(pk));send.assert_not_called()
            with patch('operations.sender.timezone.now',return_value=row.next_attempt_at+timedelta(seconds=1)):
                self.assertTrue(deliver(pk));self.assertFalse(deliver(pk))
            self.assertEqual(send.call_count,1)
            self.assertNotIn('parse_mode',send.call_args.args[2])
            self.assertTrue(send.call_args.args[2]['disable_web_page_preview'])
    def test_disabled_categories_do_not_block_other_notifications(self):
        queue('first','forms','A form');second=queue('second','crm','A lead')
        self.config.forms_enabled=False;self.config.save()
        with patch('operations.sender.api',return_value={'message_id':42}):self.assertEqual(flush(),1)
        self.assertIsNotNone(TelegramMessage.objects.get(pk=second).sent_at)
    def test_error_summary_never_forwards_raw_log_message_query_or_traceback(self):
        record=logging.LogRecord('payments.checkout',logging.ERROR,'private.py',1,'password=TOP_SECRET sk_live_SENSITIVE %s',('body contents',),(RuntimeError,RuntimeError('exception with secret'),None))
        record.request=SimpleNamespace(path='/secret/TOP_SECRET',resolver_match=SimpleNamespace(route='api/payments/checkout/'))
        handler=SafeTelegramErrorHandler();handler.emit(record);handler.emit(record)
        self.assertEqual(TelegramMessage.objects.filter(category='errors').count(),1)
        body=TelegramMessage.objects.get(category='errors').text
        self.assertIn('RuntimeError',body);self.assertIn('api/payments/checkout/',body)
        for secret in ['TOP_SECRET','SENSITIVE','body contents','exception with secret','private.py']:self.assertNotIn(secret,body)
    def test_provider_error_storage_does_not_contain_bot_url_or_raw_description(self):
        config=SimpleNamespace(token=TOKEN)
        error=HTTPError('https://api.telegram.org/bot'+TOKEN+'/sendMessage',403,'secret provider error',{},io.BytesIO(json.dumps({'description':TOKEN}).encode()))
        with patch('operations.sender.urlopen',side_effect=error):
            with self.assertRaises(TelegramFailure) as result:api('sendMessage',config,{'chat_id':'-1','text':'safe'})
        self.assertEqual(result.exception.code,'chat_unavailable')
        self.assertNotIn(TOKEN,str(result.exception))
    def test_worker_requires_authorized_identity(self):
        client=APIClient()
        self.assertEqual(client.get('/api/academy/internal/telegram/').status_code,403)
        with patch.dict('os.environ',{'CRON_SECRET':'local-worker-secret'}),patch('operations.views.flush',return_value=3):
            result=client.get('/api/academy/internal/telegram/',HTTP_AUTHORIZATION='Bearer local-worker-secret')
        self.assertEqual(result.status_code,200);self.assertEqual(result.data['telegram_sent'],3)
    def test_admin_token_is_write_only_and_superuser_only(self):
        admin=get_user_model().objects.create_superuser('telegram-admin','admin@example.com','test-only-password');self.client.force_login(admin)
        response=self.client.get('/admin/operations/telegramsettings/1/change/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,TOKEN);self.assertNotContains(response,self.config.token_ciphertext)
        staff=get_user_model().objects.create_user('other-staff',is_staff=True);self.client.force_login(staff)
        self.assertEqual(self.client.get('/admin/operations/telegramsettings/1/change/').status_code,403)
        self.assertNotEqual(self.config.token_ciphertext,TOKEN);self.assertEqual(decrypt(self.config.token_ciphertext),TOKEN)

    def test_environment_credentials_and_admin_chat_discovery(self):
        admin=get_user_model().objects.create_superuser('setup-admin','setup@example.com','local-test-password');self.client.force_login(admin)
        updates=[{'message':{'chat':{'id':-100555111,'title':'Operations group'},'text':'PRIVATE CHAT BODY'}}]
        with patch('operations.admin.api',return_value=updates) as bot:
            response=self.client.post('/admin/operations/telegramsettings/',{'action':'find_chats','_selected_action':['1']},follow=True)
        self.assertEqual(bot.call_args.args[0],'getUpdates')
        self.assertContains(response,'-100555111');self.assertNotContains(response,'PRIVATE CHAT BODY')
        with patch('operations.admin.api',return_value={'message_id':7}) as bot:
            response=self.client.post('/admin/operations/telegramsettings/',{'action':'send_test','_selected_action':['1']},follow=True)
        self.assertEqual(bot.call_args.args[0],'sendMessage')
        self.assertIn('connection test',bot.call_args.args[2]['text'])
        self.assertNotContains(response,TOKEN)
        TelegramSettings.objects.all().delete()
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':TOKEN,'TELEGRAM_CHAT_ID':'-100222333'}):
            pk=queue('env:test','forms','Environment connection')
        self.assertIsNotNone(pk);self.assertEqual(TelegramMessage.objects.get(pk=pk).chat_id,'-100222333')
