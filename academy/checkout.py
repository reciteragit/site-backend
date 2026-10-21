from datetime import timedelta
import stripe
from django.db import transaction
from django.utils import timezone
from .models import Order


def create_session(gateway, order, params):
    try:
        return gateway.v1.checkout.sessions.create(params, {'idempotency_key':f'recitera-academy-{order.id}'})
    except (stripe.IdempotencyError, stripe.InvalidRequestError) as exc:
        if not isinstance(exc, stripe.IdempotencyError) and getattr(exc, 'param', None) != 'expires_at' and 'expires_at' not in str(exc):
            raise
        # Requests rejected by the previous API shape can retain their key. First
        # recover a successful session whose response may have been lost, so a
        # migration never creates a second payable session for the same order.
        sessions = gateway.v1.checkout.sessions.list({'created':{'gte':int((order.created_at-timedelta(minutes=1)).timestamp())},'limit':100})
        for index, session in enumerate(sessions.auto_paging_iter()):
            if index >= 500:
                raise ValueError('Checkout recovery requires operator review.')
            metadata = session.metadata.to_dict() if hasattr(session.metadata, 'to_dict') else session.metadata
            if metadata.get('academy_order_id') != str(order.id):
                continue
            if session.client_reference_id != str(order.id) or session.amount_total != int(order.amount*100) or session.currency != order.currency.lower() or bool(session.livemode) != (order.mode == 'live'):
                raise ValueError('Existing checkout does not match order.')
            if session.status == 'open':
                return session
            if session.status == 'complete':
                raise ValueError('Existing checkout awaits payment reconciliation.')
        with transaction.atomic():
            current = Order.objects.select_for_update().get(pk=order.pk)
            now = timezone.now()
            if current.status != 'held' or current.expires_at <= now:
                raise ValueError('Reservation is no longer eligible for checkout preparation.')
            # No previous open/complete Stripe session exists. Renew a short
            # preparation window under the lock; concurrent retries share it.
            if current.expires_at < now + timedelta(minutes=36):
                current.expires_at = now + timedelta(minutes=66)
                current.save(update_fields=['expires_at'])
            order.expires_at = current.expires_at
        params = {**params, 'expires_at':int((order.expires_at-timedelta(minutes=5)).timestamp())}
        key = f'recitera-academy-v3-{order.id}-{params["expires_at"]}'
        return gateway.v1.checkout.sessions.create(params, {'idempotency_key':key})
