from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import Slot, Booking, Order, TeachingProfile
from .notifications import queue_confirmation


def valid_meeting(provider,url):
    try:
        parsed=urlsplit(url)
        port=parsed.port
    except ValueError:return False
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or port not in [None,443]:
        return False
    host=parsed.hostname.lower()
    if provider == 'lms' and host == 'lms.recitera.com':
        return True
    if not parsed.path.strip('/'):
        return False
    return (provider=='meet' and host=='meet.google.com') or (provider=='zoom' and any(host==domain or host.endswith('.'+domain) for domain in ['zoom.us','zoom.com'])) or (provider=='lms' and host=='lms.recitera.com')


def lock_teachers(ids):
    # All mutations acquire these locks first, in the same order, including webhooks.
    return list(TeachingProfile.objects.select_for_update().filter(pk__in=ids).order_by('pk'))


def expire_holds():
    # Stripe sessions expire before our hold; five extra minutes allow webhook delivery.
    for order_id in list(Order.objects.filter(status__in=['held','pending'],expires_at__lt=timezone.now()).values_list('pk',flat=True)[:100]):
        with transaction.atomic():
            ids=list(Booking.objects.filter(order_id=order_id).values_list('slot__teacher_id',flat=True))
            lock_teachers(ids)
            order=Order.objects.select_for_update().get(pk=order_id)
            if order.status in ['held','pending'] and order.expires_at<timezone.now():
                order.status='expired';order.save(update_fields=['status'])
                order.bookings.filter(status='held').update(status='expired')


def available_queryset():
    return Slot.objects.filter(active=True,teacher__approved=True,teacher__user__is_active=True,teacher__teacher__published=True,starts_at__gt=timezone.now()+timedelta(hours=1)).exclude(bookings__status__in=['held','confirmed'])


def process_event(event):
    from catalog.payment_models import StripeEvent
    obj=event['data']['object']; key=obj.get('metadata',{}).get('academy_order_id')
    if not key: return None
    try:
        with transaction.atomic():
            ids=list(Booking.objects.filter(order_id=key).values_list('slot__teacher_id',flat=True))
            lock_teachers(ids)
            order=Order.objects.select_for_update().filter(pk=key).first()
            if not order: return {'error':'Order not found.'},400
            if StripeEvent.objects.filter(event_id=event['id']).exists(): return {'received':True},200
            if (order.stripe_session_id and order.stripe_session_id!=obj.get('id')) or obj.get('client_reference_id')!=str(order.id) or obj.get('amount_total')!=int(order.amount*100) or obj.get('currency')!='cad' or bool(event.get('livemode'))!=(order.mode=='live'):
                return {'error':'Payment does not match booking order.'},400
            successful=event['type'] in ['checkout.session.completed','checkout.session.async_payment_succeeded'] and obj.get('payment_status')=='paid'
            if successful and order.status not in ['paid','payment_review']:
                bookings=list(order.bookings.select_related('slot__teacher__user','student','order'))
                slot_ids=[b.slot_id for b in bookings]
                conflicts=Booking.objects.filter(slot_id__in=slot_ids,status__in=['held','confirmed']).exclude(order=order).exists()
                if conflicts or any(b.slot.starts_at<=timezone.now() or not b.slot.active or not b.slot.teacher.approved for b in bookings):
                    order.status='payment_review';order.bookings.update(status='payment_review')
                else:
                    order.status='paid'
                    for booking in bookings:
                        booking.status='confirmed';booking.save(update_fields=['status'])
                        queue_confirmation(booking)
                order.paid_at=timezone.now();order.stripe_session_id=obj['id'];order.save()
                if order.status=='paid':
                    from .models import CartItem
                    CartItem.objects.filter(user=order.user,slot_id__in=slot_ids).delete()
            elif order.status not in ['paid','payment_review'] and event['type'] in ['checkout.session.expired','checkout.session.async_payment_failed']:
                order.status='failed' if event['type'].endswith('failed') else 'expired';order.save(update_fields=['status'])
                order.bookings.filter(status='held').update(status=order.status)
            StripeEvent.objects.create(event_id=event['id'],event_type=event['type'])
    except (ValueError, DjangoValidationError, serializers.ValidationError): return {'error':'Invalid booking event.'},400
    return {'received':True},200
