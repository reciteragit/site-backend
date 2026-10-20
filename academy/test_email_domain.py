from io import StringIO
from unittest.mock import patch,MagicMock
from django.core.management import call_command
from django.test import SimpleTestCase,override_settings

@override_settings(RESEND_API_KEY='re_fixture')
class EmailDomainTests(SimpleTestCase):
    @patch('academy.management.commands.check_email_domain.send_mail')
    @patch('academy.management.commands.check_email_domain.urlopen')
    def test_domain_check_does_not_send_without_explicit_recipient(self,request,send):
        response=MagicMock();response.read.return_value=b'{"id":"domain_fixture","name":"recitera.com","status":"verified"}'
        request.return_value.__enter__.return_value=response
        out=StringIO();call_command('check_email_domain',domain_id='domain_fixture',verify=True,stdout=out)
        self.assertIn('Sender verified',out.getvalue());self.assertEqual(request.call_count,1);send.assert_not_called()
    @patch('academy.management.commands.check_email_domain.send_mail',return_value=1)
    @patch('academy.management.commands.check_email_domain.urlopen')
    def test_authorized_test_recipient_is_used_explicitly(self,request,send):
        response=MagicMock();response.read.return_value=b'{"id":"domain_fixture","name":"recitera.com","status":"verified"}'
        request.return_value.__enter__.return_value=response
        out=StringIO();call_command('check_email_domain',domain_id='domain_fixture',test_recipient='owner@example.com',stdout=out)
        self.assertIn('accepted by email provider',out.getvalue());self.assertEqual(send.call_args.args[3],['owner@example.com'])
    @override_settings(RESEND_API_KEY='')
    @patch('academy.management.commands.check_email_domain.urlopen')
    def test_absent_key_does_not_access_network(self,request):
        out=StringIO();call_command('check_email_domain',stdout=out);request.assert_not_called();self.assertIn('not configured',out.getvalue())
