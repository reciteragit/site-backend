from django.core.management.base import BaseCommand
from operations.sender import flush
class Command(BaseCommand):
    help='Send due Telegram notifications using the configured connection.'
    def handle(self,*args,**options):self.stdout.write(f'Telegram messages sent: {flush(8)}')
