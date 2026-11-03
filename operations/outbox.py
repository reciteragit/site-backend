import os,re
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from django.db import transaction
from django.utils import timezone
from .models import TelegramSettings,TelegramMessage
from catalog.stripe_gateway import decrypt


def connection():
    row=TelegramSettings.objects.first()
    token=decrypt(row.token_ciphertext) if row and row.token_ciphertext else os.getenv('TELEGRAM_BOT_TOKEN','')
    chat=row.chat_id if row and row.chat_id else os.getenv('TELEGRAM_CHAT_ID','')
    thread=row.thread_id if row else None
    return SimpleNamespace(enabled=row.enabled if row else bool(token and chat),token=token,chat_id=chat,thread_id=thread,timezone=row.timezone if row else os.getenv('TELEGRAM_TIMEZONE','Asia/Tehran'),include_contacts=row.include_contact_details if row else False,row=row)


def valid_connection(config):
    return bool(re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',config.token) and re.fullmatch(r'(?:-?\d+|@[A-Za-z][A-Za-z0-9_]{4,})',config.chat_id))


def clean(value,limit=180):return ' '.join(str(value).split())[:limit]


def queue(key,category,title,details=None,admin_path='',contact=None):
    # A failed/disabled notification integration must never break a checkout or form.
    try:
        with transaction.atomic():
            config=connection()
            if not config.enabled or not valid_connection(config):return None
            if config.row and not getattr(config.row,category+'_enabled',False):return None
            zone=ZoneInfo(config.timezone)
            lines=['RECITERA · '+clean(title), 'Event: '+clean(category), 'Time ('+config.timezone+'): '+timezone.now().astimezone(zone).isoformat()]
            for label,value in (details or {}).items():
                if isinstance(value,datetime):value=value.astimezone(zone).isoformat()+' ('+config.timezone+')'
                lines.append(clean(label,60)+': '+clean(value))
            if config.include_contacts:
                for label,value in (contact or {}).items():
                    if value and label in ['Name','Email','Phone']:lines.append(label+': '+clean(value))
            if admin_path.startswith('/admin/') and '?' not in admin_path and '#' not in admin_path:lines.append('Admin: https://site-backend-one.vercel.app'+admin_path)
            message,_=TelegramMessage.objects.get_or_create(key=key[:200],defaults={'category':category,'text':'\n'.join(lines)[:3900],'chat_id':config.chat_id,'thread_id':config.thread_id})
            return message.pk
    except Exception:return None


def email_event(app,model,pk,kind,success,error=''):
    state='sent' if success else 'failed'
    return queue(f'email:{app}:{model}:{pk}:{state}','emails','Email '+state,{'Delivery':pk,'Type':kind,'Result':state,'Error type':error if not success else ''},f'/admin/{app}/{model}/{pk}/change/')
