from django.core.management.base import BaseCommand
from academy.notifications import flush_mail

class Command(BaseCommand):
    help='Retry queued booking confirmation emails using the configured email provider.'
    def handle(self,*args,**options):
        self.stdout.write(f'Sent {flush_mail(50)} queued emails.')
