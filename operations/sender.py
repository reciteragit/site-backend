import json,time,re
from datetime import timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .outbox import connection,valid_connection
from .models import TelegramMessage


class TelegramFailure(Exception):
    def __init__(self,code,retry_after=None):self.code=code;self.retry_after=retry_after


def api(method,config,payload):
    # Never surface a raw exception/URL: Telegram's URL contains the bot credential.
    if not config.token:raise TelegramFailure('credentials_missing')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',config.token):raise TelegramFailure('credentials_invalid')
    if method not in ['sendMessage','getUpdates']:raise TelegramFailure('unsupported_operation')
    request=Request('https://api.telegram.org/bot'+config.token+'/'+method,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(request,timeout=5) as response:data=json.loads(response.read(200000))
        if data.get('ok') is not True:raise TelegramFailure('telegram_rejected')
        return data.get('result')
    except HTTPError as error:
        code='rate_limited' if error.code==429 else 'credentials_invalid' if error.code==401 else 'chat_unavailable' if error.code in [400,403] else 'telegram_api_error'
        retry=None
        if error.code==429:
            try:retry=min(86400,max(1,int(json.loads(error.read(10000)).get('parameters',{}).get('retry_after',60))))
            except Exception:retry=60
        raise TelegramFailure(code,retry) from None
    except TelegramFailure:raise
    except Exception:raise TelegramFailure('network_or_response_error') from None


def deliver(pk):
    with transaction.atomic():
        row=TelegramMessage.objects.select_for_update().get(pk=pk)
        now=timezone.now()
        if row.sent_at or row.dismissed_at or (row.next_attempt_at and row.next_attempt_at>now) or (row.leased_until and row.leased_until>now):return False
        try:config=connection()
        except Exception:return False
        if not config.enabled or not valid_connection(config) or (config.row and not getattr(config.row,row.category+'_enabled',False)):return False
        row.leased_until=now+timedelta(minutes=2);row.attempts+=1;row.save(update_fields=['leased_until','attempts'])
    payload={'chat_id':row.chat_id,'text':row.text,'disable_web_page_preview':True}
    if row.thread_id:payload['message_thread_id']=row.thread_id
    try:
        result=api('sendMessage',config,payload)
        message_id=result.get('message_id') if isinstance(result,dict) else None
        if not isinstance(message_id,int):raise TelegramFailure('invalid_response')
    except TelegramFailure as error:
        delay=error.retry_after or min(3600,60*(2**min(row.attempts,6)))
        TelegramMessage.objects.filter(pk=pk).update(leased_until=None,last_error=error.code,next_attempt_at=timezone.now()+timedelta(seconds=delay));return False
    TelegramMessage.objects.filter(pk=pk).update(sent_at=timezone.now(),leased_until=None,last_error='',next_attempt_at=None,telegram_message_id=message_id)
    return True


def flush(limit=8):
    config=connection()
    if not config.enabled or not valid_connection(config):return 0
    categories=[name for name in ['forms','crm','bookings','payments','accounts','admin','emails','errors'] if not config.row or getattr(config.row,name+'_enabled',False)]
    now=timezone.now();deadline=time.monotonic()+10
    rows=TelegramMessage.objects.filter(sent_at__isnull=True,dismissed_at__isnull=True,category__in=categories).filter(Q(next_attempt_at__isnull=True)|Q(next_attempt_at__lte=now)).filter(Q(leased_until__isnull=True)|Q(leased_until__lt=now)).order_by('attempts','pk').values_list('pk',flat=True)[:limit]
    sent=0
    for pk in list(rows):
        if time.monotonic()>deadline:break
        if deliver(pk):sent+=1
        else:break
    return sent
