from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone
from .models import EmailDelivery


def calendar(booking):
    def escape(value): return str(value).replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;').replace('\r','')
    def stamp(value): return value.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    cancelled=booking.status=='cancelled'
    stamp_time=booking.cancellation_request.decided_at if cancelled else booking.order.paid_at or timezone.now()
    lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Recitera//Class booking//EN','METHOD:CANCEL' if cancelled else 'METHOD:PUBLISH','BEGIN:VEVENT',f'UID:{booking.id}@recitera.com',f'DTSTAMP:{stamp(stamp_time)}',f'DTSTART:{stamp(booking.slot.starts_at)}',f'DTEND:{stamp(booking.slot.ends_at)}',f'SUMMARY:{escape("Recitera class with "+booking.teacher_name)}',f'DESCRIPTION:{escape("Join your class: "+booking.meeting_url)}',f'URL:{booking.meeting_url}','STATUS:CANCELLED' if cancelled else 'STATUS:CONFIRMED',f'SEQUENCE:{1 if cancelled else 0}','END:VEVENT','END:VCALENDAR']
    # RFC 5545 line folding, limiting UTF-8 octets rather than characters.
    folded=[]
    for line in lines:
        piece=''
        for char in line:
            if len((piece+char).encode())>73:
                folded.append(piece);piece=' '+char
            else: piece+=char
        folded.append(piece)
    return '\r\n'.join(folded)+'\r\n'


def queue_confirmation(booking):
    from .booking_notices import queue_reminders
    queue_reminders(booking)
    for recipient, tz in [(booking.student.email,booking.student_timezone),(booking.slot.teacher.user.email,booking.teacher_timezone)]:
        EmailDelivery.objects.get_or_create(booking=booking,recipient=recipient,defaults={'recipient_timezone':tz})


def deliver(delivery_id):
    # Database lease prevents concurrent webhook/cron workers sending the same email.
    with transaction.atomic():
        delivery=EmailDelivery.objects.select_for_update().select_related('booking__slot','booking__order').get(pk=delivery_id)
        if delivery.sent_at or (delivery.leased_until and delivery.leased_until>timezone.now()) or delivery.booking.status!='confirmed': return False
        if not settings.DEFAULT_FROM_EMAIL or (settings.EMAIL_BACKEND=='django.core.mail.backends.smtp.EmailBackend' and not settings.EMAIL_HOST) or (settings.EMAIL_BACKEND=='academy.email_backend.ResendBackend' and not settings.RESEND_API_KEY):
            delivery.last_error='Email service is not configured';delivery.save(update_fields=['last_error']);return False
        delivery.leased_until=timezone.now()+timedelta(minutes=2)
        delivery.attempts+=1;delivery.save(update_fields=['leased_until','attempts'])
    booking=delivery.booking
    tz=ZoneInfo(delivery.recipient_timezone)
    start=booking.slot.starts_at.astimezone(tz).strftime('%A, %d %B %Y at %H:%M %Z')
    end=booking.slot.ends_at.astimezone(tz).strftime('%H:%M %Z')
    sandbox='[TEST BOOKING] ' if booking.order.mode=='test' else ''
    text=f'{sandbox}Your Recitera class is confirmed.\n\nTeacher: {booking.teacher_name}\nTime: {start} – {end}\nTime zone: {delivery.recipient_timezone}\nJoin class: {booking.meeting_url}\nBooking reference: {booking.id}\n\n'+('This is a Stripe test booking; no real payment was collected.\n' if sandbox else '')+'Keep your class link private. A calendar invitation is attached.'
    message=EmailMessage(f'{sandbox}Recitera class confirmation',text,settings.DEFAULT_FROM_EMAIL,[delivery.recipient],headers={'Message-ID':f'<booking-{booking.id}-{delivery.pk}@recitera.com>'})
    message.attach('recitera-class.ics',calendar(booking),'text/calendar')
    try:
        if message.send(fail_silently=False)!=1: raise RuntimeError('Mail backend did not accept email')
    except Exception as error:
        EmailDelivery.objects.filter(pk=delivery_id).update(leased_until=None,last_error=type(error).__name__)
        return False
    EmailDelivery.objects.filter(pk=delivery_id).update(sent_at=timezone.now(),leased_until=None,last_error='')
    return True


def flush_mail(limit=10,order_id=None):
    import time
    deadline=time.monotonic()+20
    pending=EmailDelivery.objects.filter(sent_at__isnull=True,booking__status='confirmed').filter(models_free_lease())
    if order_id:pending=pending.filter(booking__order_id=order_id)
    ids=list(pending.order_by('attempts','pk').values_list('pk',flat=True)[:limit])
    sent=0
    for pk in ids:
        if time.monotonic()>deadline:break
        sent+=deliver(pk)
    return sent


def models_free_lease():
    from django.db.models import Q
    return Q(leased_until__isnull=True)|Q(leased_until__lt=timezone.now())
