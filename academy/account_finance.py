"""Private, account-linked payment history; never match ownership by email."""
from decimal import Decimal
from django.db.models import Sum, Count
from rest_framework.response import Response
from catalog.payment_models import PaymentOrder
from .models import Order
from .services import expire_holds
from .views import AcademyView


class AccountFinance(AcademyView):
    def get(self, request):
        expire_holds()
        classes = Order.objects.filter(user=request.user)
        purchases = PaymentOrder.objects.filter(buyer=request.user)
        totals = {}
        for queryset in [classes, purchases]:
            for group in queryset.values('currency', 'mode', 'status').annotate(total=Sum('amount'), discount=Sum('discount_amount'), count=Count('pk')):
                if group['mode'] == 'test':
                    continue
                currency = group['currency']
                row = totals.setdefault(currency, {'currency': currency, 'paid': Decimal('0'), 'pending': Decimal('0'), 'saved': Decimal('0'), 'paid_count': 0})
                if group['status'] == 'paid':
                    row['paid'] += group['total'] or 0
                    row['saved'] += group['discount'] or 0
                    row['paid_count'] += group['count']
                elif group['status'] in ['held', 'pending', 'registered']:
                    row['pending'] += group['total'] or 0
        transactions = []
        for kind, queryset in [('classes', classes), ('purchase', purchases)]:
            for order in queryset.order_by('-created_at')[:100]:
                transactions.append({
                    'id': str(order.pk), 'kind': kind if kind == 'classes' else order.purpose,
                    'title': 'Class booking' if kind == 'classes' else order.title,
                    'date': order.created_at.isoformat(), 'status': order.status,
                    'amount': str(order.amount), 'subtotal': str(order.subtotal or order.amount),
                    'discount_amount': str(order.discount_amount), 'discount_code': order.discount_code,
                    'currency': order.currency, 'mode': order.mode,
                })
        transactions.sort(key=lambda row: row['date'], reverse=True)
        count = classes.count() + purchases.count()
        return Response({
            'totals': [{**row, **{key: f'{row[key]:.2f}' for key in ['paid', 'pending', 'saved']}} for row in sorted(totals.values(), key=lambda row: row['currency'])],
            'transactions': transactions[:100], 'total_count': count, 'has_more': count > 100,
        }, headers={'Cache-Control': 'private, no-store'})
