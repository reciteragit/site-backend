"""Server-authoritative, cent-exact discounts shared by both checkout paths."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .discount_models import DiscountCode, normalize_code

CENT=Decimal('0.01')
ZERO=Decimal('0.00')


@dataclass(frozen=True)
class ProductLine:
    kind: str
    product_id: int
    amount: Decimal


@dataclass(frozen=True)
class DiscountQuote:
    code: str
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    amounts: list
    coupon: object = None
    def data(self):
        return {'discount_code':self.code,'subtotal':f'{self.subtotal:.2f}','discount_amount':f'{self.discount:.2f}','total':f'{self.total:.2f}','currency':'CAD'}


def calculate_discount(code,lines,user=None,*,lock=False):
    subtotal=sum((line.amount for line in lines),ZERO)
    code=normalize_code(code)
    if not code:return DiscountQuote('',subtotal,ZERO,subtotal,[line.amount for line in lines])
    query=DiscountCode.objects
    if lock:query=query.select_for_update()
    coupon=query.filter(code__iexact=code).first()
    now=timezone.now()
    if not coupon or not coupon.active or (coupon.starts_at and now<coupon.starts_at) or (coupon.ends_at and now>=coupon.ends_at):
        raise ValidationError({'discount_code':'This discount code is invalid, inactive or outside its valid dates.'})
    if coupon.allowed_user_id and (not user or not user.is_authenticated or coupon.allowed_user_id!=user.pk):
        raise ValidationError({'discount_code':'This discount code is not available for this account. Sign in with the eligible account.'})
    selections={} if coupon.all_products else {'teacher':set(coupon.teachers.values_list('pk',flat=True)),'course':set(coupon.courses.values_list('pk',flat=True)),'other':set(coupon.payment_items.values_list('pk',flat=True)),'bundle':set(coupon.bundles.values_list('pk',flat=True))}
    eligible=[i for i,line in enumerate(lines) if line.amount>0 and line.kind in ['teacher','course','other','bundle'] and (coupon.all_products or line.product_id in selections.get(line.kind,set())) and (coupon.minimum_basis!='individual_product' or line.amount>=coupon.minimum_amount)]
    base=sum((lines[i].amount for i in eligible),ZERO)
    if not base:
        raise ValidationError({'discount_code':'This code does not apply to these products or their individual prices.'})
    if coupon.minimum_basis=='eligible_subtotal' and base<coupon.minimum_amount:
        raise ValidationError({'discount_code':f'Eligible products must total at least {coupon.minimum_amount:.2f} CAD before discount.'})
    discount=min(base,(base*coupon.value/100).quantize(CENT,rounding=ROUND_HALF_UP) if coupon.discount_type=='percentage' else coupon.value)
    if discount<=0:raise ValidationError({'discount_code':'This code does not reduce the price of these products.'})
    total=subtotal-discount
    if ZERO<total<Decimal('0.50'):
        raise ValidationError({'discount_code':'The remaining payment must be at least 0.50 CAD, or fully covered by the discount.'})
    # Proportional allocation with largest remainders keeps line amounts and the
    # final Stripe amount exactly equal, including fixed discounts on mixed carts.
    exact={i:discount*lines[i].amount/base for i in eligible}
    shares={i:exact[i].quantize(CENT,rounding=ROUND_DOWN) for i in eligible}
    cents=int((discount-sum(shares.values(),ZERO))/CENT)
    for i in sorted(eligible,key=lambda i:(-(exact[i]-shares[i]),i))[:cents]:shares[i]+=CENT
    amounts=[line.amount-shares.get(i,ZERO) for i,line in enumerate(lines)]
    return DiscountQuote(coupon.code,subtotal,discount,total,amounts,coupon)
