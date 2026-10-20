import base64
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings
from .email_backend import ResendBackend, ResendDeliveryError


@override_settings(RESEND_API_KEY='re_test_fixture',EMAIL_TIMEOUT=5)
class ResendTests(SimpleTestCase):
    def message(self):
        message=EmailMessage('Class confirmation','Your private class link: https://meet.google.com/abc-defg-hij','info@recitera.com',['student@example.com'],headers={'Message-ID':'<booking-fixture@recitera.com>'})
        message.attach('class.ics','BEGIN:VCALENDAR\r\nEND:VCALENDAR','text/calendar')
        return message
    @patch('academy.email_backend.urlopen')
    def test_sends_private_text_and_base64_calendar_with_provider_idempotency(self,send):
        response=MagicMock(status=200);response.read.return_value=b'{"id":"email_fixture"}'
        send.return_value.__enter__.return_value=response
        backend=ResendBackend();message=self.message()
        self.assertEqual(backend.send_messages([message]),1)
        request=send.call_args.args[0];payload=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.resend.com/emails')
        self.assertEqual(payload['from'],'info@recitera.com')
        self.assertEqual(payload['to'],['student@example.com'])
        self.assertEqual(base64.b64decode(payload['attachments'][0]['content']).decode(),'BEGIN:VCALENDAR\r\nEND:VCALENDAR')
        key=request.get_header('Idempotency-key')
        backend.send_messages([message]);self.assertEqual(key,send.call_args.args[0].get_header('Idempotency-key'))
        message.body+=' Updated room.'
        backend.send_messages([message]);self.assertNotEqual(key,send.call_args.args[0].get_header('Idempotency-key'))
        self.assertEqual(send.call_args.kwargs['timeout'],5)
    @patch('academy.email_backend.urlopen')
    def test_unverified_sender_or_provider_error_is_not_reported_as_sent(self,send):
        send.side_effect=HTTPError('https://api.resend.com/emails',403,'Forbidden',{},None)
        with self.assertRaises(ResendDeliveryError) as error:ResendBackend().send_messages([self.message()])
        self.assertNotIn('re_test_fixture',str(error.exception))
        self.assertEqual(ResendBackend(fail_silently=True).send_messages([self.message()]),0)
    @patch('academy.email_backend.urlopen')
    def test_success_requires_provider_message_id(self,send):
        response=MagicMock(status=200);response.read.return_value=b'{}';send.return_value.__enter__.return_value=response
        with self.assertRaises(ResendDeliveryError):ResendBackend().send_messages([self.message()])
    @override_settings(RESEND_API_KEY='')
    @patch('academy.email_backend.urlopen')
    def test_missing_key_never_attempts_delivery(self,send):
        with self.assertRaises(ResendDeliveryError):ResendBackend().send_messages([self.message()])
        send.assert_not_called()
