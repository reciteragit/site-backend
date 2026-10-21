from datetime import timedelta
import stripe


def create_session(gateway, order, params):
    try:
        return gateway.v1.checkout.sessions.create(params, {'idempotency_key':f'recitera-academy-{order.id}'})
    except stripe.IdempotencyError:
        # Requests rejected by the previous API shape can retain their key. First
        # recover a successful session whose response may have been lost, so a
        # migration never creates a second payable session for the same order.
        sessions = gateway.v1.checkout.sessions.list({'created':{'gte':int((order.created_at-timedelta(minutes=1)).timestamp())},'limit':100})
        for index, session in enumerate(sessions.auto_paging_iter()):
            if index >= 500:
                raise ValueError('Checkout recovery requires operator review.')
            if session.metadata.get('academy_order_id') != str(order.id):
                continue
            if session.client_reference_id != str(order.id) or session.amount_total != int(order.amount*100) or session.currency != order.currency.lower() or bool(session.livemode) != (order.mode == 'live'):
                raise ValueError('Existing checkout does not match order.')
            if session.status == 'open':
                return session
            if session.status == 'complete':
                raise ValueError('Existing checkout awaits payment reconciliation.')
        return gateway.v1.checkout.sessions.create(params, {'idempotency_key':f'recitera-academy-v2-{order.id}'})
