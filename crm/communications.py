from datetime import timedelta
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import Communication


def deliver(pk):
    with transaction.atomic():
        item=Communication.objects.select_for_update(of=('self',)).select_related('lead','booking__slot','trial_request').get(pk=pk)
        now=timezone.now()
        if item.sent_at or item.suppressed_at or item.due_at>now or (item.leased_until and item.leased_until>now):return False
        blocked=item.lead.do_not_contact or item.lead.stage in ['converted','dropped']
        if item.kind=='trial_followup':
            record=getattr(item.booking,'crm_trial',None)
            blocked=blocked or item.booking.status!='confirmed' or item.booking.slot.ends_at>now or not record or bool(record.feedback_at)
        if item.kind=='trial_received' and item.trial_request and item.trial_request.created_at<now-timedelta(days=2):blocked=True
        if blocked:
            item.suppressed_at=now;item.save(update_fields=['suppressed_at']);return False
        item.attempts+=1;item.leased_until=now+timedelta(minutes=2);item.save(update_fields=['attempts','leased_until'])
    if item.kind=='trial_received':
        title='We received your Recitera trial request'
        from .services import claim_token
        from urllib.parse import urlencode
        token=claim_token(item.trial_request) if item.trial_request_id else ''
        link='https://www.recitera.com/account?'+urlencode({'trial_claim':token}) if token else 'https://www.recitera.com/account'
        text='Thank you for requesting a trial. Our team will contact you to help choose a teacher and time. A request does not reserve a class.\n\nConnect this request to your account by opening the link and signing in with the email used for the request: '+link+'\n\nYou can also choose an available free trial at https://www.recitera.com/teachers\n'
    else:
        title='How did your scheduled Recitera trial go?'
        text='We would like to hear how your scheduled trial went. If you could not attend or need help choosing your next step, please tell us.\n\nSign in to share feedback: https://www.recitera.com/account#trial-feedback-'+str(item.booking_id)+'\nExplore teachers and regular classes: https://www.recitera.com/teachers\nExplore recorded courses and available packages: https://www.recitera.com/courses\n'
    text+='\nQuestions? Reply to info@recitera.com. You can ask our team to stop further follow-up messages.\n'
    message=EmailMessage('Recitera — '+title,text,settings.DEFAULT_FROM_EMAIL,[item.recipient],reply_to=['info@recitera.com'],headers={'Message-ID':f'<crm-message-{item.pk}@recitera.com>'})
    try:
        if message.send(fail_silently=False)!=1:raise RuntimeError('Email not accepted')
    except Exception as error:
        Communication.objects.filter(pk=pk).update(leased_until=None,last_error=type(error).__name__);return False
    Communication.objects.filter(pk=pk).update(sent_at=timezone.now(),leased_until=None,last_error='');return True


def flush(limit=5):
    import time
    from .services import sync_sources
    sync_sources(200)
    now=timezone.now();deadline=time.monotonic()+12
    ids=Communication.objects.filter(sent_at__isnull=True,suppressed_at__isnull=True,due_at__lte=now).filter(Q(leased_until__isnull=True)|Q(leased_until__lt=now)).order_by('attempts','due_at').values_list('pk',flat=True)[:limit]
    sent=0
    for pk in list(ids):
        if time.monotonic()>deadline:break
        sent+=deliver(pk)
    return sent
