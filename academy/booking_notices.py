from datetime import timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import Booking, BookingNotice
from .notifications import calendar


def recipients(booking):
    return [(booking.student.email, booking.student_timezone), (booking.slot.teacher.user.email, booking.teacher_timezone)]


def queue_reminders(booking):
    now = timezone.now()
    thresholds=[('reminder_24h',timedelta(hours=24),timedelta(minutes=30)),('reminder_30m',timedelta(minutes=30),timedelta(minutes=25 if booking.slot.kind=='trial' else 30))]
    if booking.slot.kind=='trial':thresholds.append(('reminder_5m',timedelta(minutes=5),timedelta(minutes=5)))
    for kind, interval, grace in thresholds:
        due = booking.slot.starts_at - interval
        # Classes booked after a reminder's threshold do not receive a misleading late reminder.
        if (booking.order.paid_at or now) > due or due + grace <= now:
            continue
        for recipient, zone in recipients(booking):
            BookingNotice.objects.get_or_create(booking=booking, recipient=recipient, kind=kind, defaults={'recipient_timezone':zone, 'due_at':due, 'expires_at':min(due+grace,booking.slot.starts_at)})


def queue_cancellation(booking, kind):
    targets = [(booking.slot.teacher.user.email,booking.teacher_timezone)] if kind == 'cancellation_request' else recipients(booking)
    for recipient, zone in targets:
        BookingNotice.objects.get_or_create(booking=booking,recipient=recipient,kind=kind,defaults={'recipient_timezone':zone,'due_at':timezone.now()})


def deliver_notice(pk):
    with transaction.atomic():
        notice=BookingNotice.objects.select_for_update().select_related('booking__slot__teacher__user','booking__student','booking__order').get(pk=pk)
        now=timezone.now()
        if notice.sent_at or notice.due_at>now or (notice.expires_at and notice.expires_at<=now) or (notice.leased_until and notice.leased_until>now):return False
        booking=notice.booking
        if notice.kind.startswith('reminder') and (booking.status!='confirmed' or booking.slot.starts_at<=now):
            notice.expires_at=now;notice.save(update_fields=['expires_at']);return False
        if notice.kind=='cancellation_request' and (booking.status!='confirmed' or booking.cancellation_request.status!='pending' or booking.slot.starts_at<=now):
            notice.expires_at=now;notice.save(update_fields=['expires_at']);return False
        if notice.kind=='cancellation_approved' and booking.status!='cancelled':
            notice.expires_at=now;notice.save(update_fields=['expires_at']);return False
        notice.leased_until=now+timedelta(minutes=2);notice.attempts+=1;notice.save(update_fields=['leased_until','attempts'])
    start=booking.slot.starts_at.astimezone(ZoneInfo(notice.recipient_timezone)).strftime('%A, %d %B %Y at %H:%M %Z')
    account='https://www.recitera.com/account'
    if notice.recipient==booking.slot.teacher.user.email:account+='/teaching#booking-'+str(booking.pk)
    title={'reminder_5m':'Trial reminder: 5 minutes','reminder_24h':'Class reminder: 24 hours','reminder_30m':'Class reminder: 30 minutes','cancellation_request':'Class cancellation request — approval needed','cancellation_approved':'Class cancelled','cancellation_declined':'Cancellation request declined'}[notice.kind]
    text=f'Teacher: {booking.teacher_name}\nStudent: {booking.student.get_full_name()}\nClass time: {start}\nTime zone: {notice.recipient_timezone}\nBooking: {booking.id}\n\n'
    if notice.kind.startswith('reminder'):
        text+='Your Recitera class is coming up.\nJoin class: '+booking.meeting_url+'\n'
    elif notice.kind=='cancellation_request':
        text+='The student requested cancellation. The class stays confirmed until you approve it in your teacher dashboard.\nReason: '+booking.cancellation_request.reason+'\n'
    elif notice.kind=='cancellation_approved':
        text+='The teacher approved the cancellation. This class is now cancelled.\nCancellation does not automatically issue a refund. Contact info@recitera.com about payment adjustments.\n'
    else:text+='The teacher declined the cancellation request. Your class remains confirmed.\nJoin class: '+booking.meeting_url+'\n'
    text+='\nOpen your account: '+account+'\n'
    message=EmailMessage('Recitera — '+title,text,settings.DEFAULT_FROM_EMAIL,[notice.recipient],headers={'Message-ID':f'<booking-notice-{notice.pk}@recitera.com>'})
    if notice.kind!='cancellation_request':message.attach('recitera-class.ics',calendar(booking),'text/calendar')
    try:
        if message.send(fail_silently=False)!=1:raise RuntimeError('Mail not accepted')
    except Exception as error:
        BookingNotice.objects.filter(pk=pk).update(leased_until=None,last_error=type(error).__name__)
        return False
    BookingNotice.objects.filter(pk=pk).update(sent_at=timezone.now(),leased_until=None,last_error='')
    return True


def flush_notices(limit=20):
    import time
    deadline=time.monotonic()+20
    now=timezone.now()
    rows=Booking.objects.filter(status='confirmed',slot__starts_at__gt=now,slot__starts_at__lte=now+timedelta(hours=25)).select_related('student','slot__teacher__user','order')
    for booking in rows.iterator():queue_reminders(booking)
    ids=BookingNotice.objects.filter(sent_at__isnull=True,due_at__lte=now).filter(Q(expires_at__isnull=True)|Q(expires_at__gt=now)).filter(Q(leased_until__isnull=True)|Q(leased_until__lt=now)).order_by('attempts','due_at').values_list('pk',flat=True)[:limit]
    sent=0
    for pk in list(ids):
        if time.monotonic()>deadline:break
        sent+=deliver_notice(pk)
    return sent
