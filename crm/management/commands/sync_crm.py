from django.core.management.base import BaseCommand
from crm.services import sync_sources
class Command(BaseCommand):
    help='Import missing trial and scholarship CRM records without sending emails.'
    def handle(self,*args,**options):
        sync_sources(100000)
        self.stdout.write('CRM sources synchronized; messages remain in the delivery queue.')
