import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help='Check the Resend sender domain, optionally request DNS verification; never prints credentials.'
    def add_arguments(self,parser):
        parser.add_argument('--domain',default='recitera.com')
        parser.add_argument('--domain-id',default=os.getenv('RESEND_DOMAIN_ID',''))
        parser.add_argument('--verify',action='store_true')
        parser.add_argument('--test-recipient',default=os.getenv('RECITERA_EMAIL_TEST_RECIPIENT',''),help='Send a test only to an explicitly authorized recipient.')
    def handle(self,*args,**options):
        key=settings.RESEND_API_KEY
        if not key:
            self.stdout.write('Resend is not configured; queued email remains pending.');return
        def request(path,method='GET'):
            req=Request('https://api.resend.com'+path,method=method,data=b'{}' if method=='POST' else None,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'Recitera-Mail-Setup/1.0'})
            with urlopen(req,timeout=10) as response:return json.loads(response.read(131072))
        verified=False
        try:
            if options['domain_id']:
                domain=request('/domains/'+options['domain_id'])
            else:
                result=request('/domains')
                domain=next((row for row in result.get('data',[]) if row.get('name')==options['domain']),{})
                if domain.get('id'):domain=request('/domains/'+domain['id'])
            if domain.get('name')!=options['domain']:
                self.stdout.write('The requested sender domain is not accessible to this API key.');return
            status=domain.get('status','unknown')
            self.stdout.write('Resend sender domain status: '+status)
            if options['verify'] and status!='verified':
                request('/domains/'+domain['id']+'/verify','POST')
                status=request('/domains/'+domain['id']).get('status','unknown')
                self.stdout.write('DNS verification requested; current domain status: '+status)
            verified=status=='verified'
        except HTTPError as error:
            self.stdout.write(f'Resend domain metadata unavailable (HTTP {error.code}). Domain-restricted keys may not permit this read.')
        except (URLError,ValueError,OSError):
            self.stdout.write('Resend domain status could not be checked; no verification or delivery is claimed.')
        recipient=options['test_recipient']
        if recipient:
            try:validate_email(recipient)
            except ValidationError:self.stdout.write('Invalid test recipient.');return
            # A verified-domain sending-only key can send even when domain-list reads are denied.
            try:
                count=send_mail('Recitera email connection test','This is an authorized test of Recitera class confirmation email delivery. No class was booked and no payment was collected.\n\nFuture confirmed booking emails will include the teacher, your local class time, private classroom link and calendar invitation.',settings.DEFAULT_FROM_EMAIL,[recipient],fail_silently=False)
                self.stdout.write('Test email accepted by email provider.' if count==1 else 'Email provider did not accept test email.')
            except Exception as error:self.stdout.write('Test email was not accepted: '+type(error).__name__)
        elif verified:self.stdout.write('Sender verified. No test message was sent.')
