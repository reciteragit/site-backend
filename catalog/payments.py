from datetime import datetime,timezone as dt_timezone
from decimal import Decimal
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
import stripe
from academy.authentication import AcademyAuthentication
from .discounts import ProductLine, calculate_discount
from .discount_models import normalize_code
from .forms import FormThrottle
from .models import Course,Teacher
from .payment_models import StripeSettings,Donor,PaymentOrder,PaymentItem,StripeEvent
from .stripe_gateway import credentials,ready,client,valid_origin

class DiscountThrottle(AnonRateThrottle):
    scope='discount_checkout'
    rate='20/min'
    def get_cache_key(self,request,view):
        identity=str(request.user.pk) if request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {'scope':self.scope,'ident':identity}


PATHWAYS={'general':'General Donations','prophet':'In honour of Prophet Muhammad (PBUH)','loved-ones':'In memory of loved ones','reciters':'In memory of Quran reciters'}
class CheckoutSerializer(serializers.Serializer):
    request_id=serializers.UUIDField()
    discount_code=serializers.CharField(max_length=40,allow_blank=True,default="")
    purpose=serializers.ChoiceField(choices=['donation','course','lesson','other','bundle'],default='donation')
    reference=serializers.CharField(max_length=200,default='general')
    amount=serializers.DecimalField(max_digits=9,decimal_places=2,min_value=Decimal('1'),max_value=Decimal('100000'),required=False)
    first_name=serializers.CharField(max_length=100)
    last_name=serializers.CharField(max_length=100,allow_blank=True,required=False,default='')
    email=serializers.EmailField(max_length=254)
    phone=serializers.CharField(max_length=40,allow_blank=True,required=False,default='')
    country=serializers.CharField(max_length=100,allow_blank=True,required=False,default='')
    comment=serializers.CharField(max_length=5000,allow_blank=True,required=False,default='')
    anonymous=serializers.BooleanField(default=False)

def price(data,config):
    purpose,ref=data['purpose'],data['reference']
    if purpose=='lesson':raise serializers.ValidationError('Choose an available class time and use the academy shopping cart to book a lesson.')
    if purpose=='donation':
        if ref not in PATHWAYS or 'amount' not in data:raise serializers.ValidationError('Choose a donation pathway and valid amount.')
        return data['amount'],PATHWAYS[ref]
    if not config or not ready(config) or not getattr(config,{'course':'courses_enabled','bundle':'courses_enabled','lesson':'lessons_enabled','other':'other_payments_enabled'}[purpose]):raise serializers.ValidationError('This payment section is not enabled.')
    if purpose=='course':
        from learning.services import purchase_courses
        courses=purchase_courses(purpose,ref)
        return courses[0].price,courses[0].title
    elif purpose=='bundle':
        from learning.services import purchase_courses
        from learning.models import CourseBundle
        purchase_courses(purpose,ref)
        item=CourseBundle.objects.get(slug=ref,published=True)
        return item.price,item.title
    elif purpose=='lesson':
        item=Teacher.objects.filter(slug=ref,published=True,currency='CAD').first()
        if item:return item.price,f'One-to-one lesson with {item.name}'
    else:
        item=PaymentItem.objects.filter(slug=ref,active=True).first()
        if item:return item.amount,item.title
    raise serializers.ValidationError('Payment item not found.')

class PaymentConfiguration(APIView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request):
        config=StripeSettings.objects.first()
        return Response({'ready':bool(config and config.donations_enabled and ready(config)),'mode':config.mode if config else 'test','currency':'CAD','amounts':[1,5,10,15,25,50]})

class PaymentItemDetails(APIView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request,purpose,reference):
        if purpose not in ['course','lesson','other','bundle']:return Response({'error':'Not found'},status=404)
        config=StripeSettings.objects.first()
        try:amount,title=price({'purpose':purpose,'reference':reference},config)
        except serializers.ValidationError:return Response({'error':'This payment is not currently available.'},status=503)
        return Response({'title':title,'amount':str(amount),'currency':'CAD','mode':config.mode},headers={'Cache-Control':'no-store'})

def product_line(purpose,reference,amount):
    if purpose=='course':item=Course.objects.filter(slug=reference).first()
    elif purpose=='other':item=PaymentItem.objects.filter(slug=reference).first()
    elif purpose=='bundle':
        from learning.models import CourseBundle
        item=CourseBundle.objects.filter(slug=reference).first()
    else:item=None
    return ProductLine(purpose,item.pk if item else 0,amount)


class DiscountPreview(APIView):
    permission_classes=[AllowAny];authentication_classes=[AcademyAuthentication];throttle_classes=[FormThrottle,DiscountThrottle]
    def post(self,request):
        class Input(serializers.Serializer):
            purpose=serializers.ChoiceField(choices=['course','other','bundle'])
            reference=serializers.CharField(max_length=200)
            discount_code=serializers.CharField(max_length=40,allow_blank=True,default='')
        s=Input(data=request.data);s.is_valid(raise_exception=True);data=s.validated_data
        amount,_=price(data,StripeSettings.objects.first())
        return Response(calculate_discount(data['discount_code'],[product_line(data['purpose'],data['reference'],amount)],request.user).data(),headers={'Cache-Control':'private, no-store'})


class Checkout(APIView):
    permission_classes=[AllowAny];authentication_classes=[AcademyAuthentication];throttle_classes=[FormThrottle,DiscountThrottle]
    def post(self,request):
        incoming=dict(request.data)
        if incoming.get('purpose') in ['course','bundle']:
            if not request.user.is_authenticated:return Response({'error':'Sign in to enrol in your course.'},status=401)
            incoming.update(email=request.user.email,first_name=request.user.first_name or 'Learner',last_name=request.user.last_name)
        serializer=CheckoutSerializer(data=incoming);serializer.is_valid(raise_exception=True);data=serializer.validated_data
        config=StripeSettings.objects.first();amount,title=price(data,config)
        if amount<=0:raise serializers.ValidationError('This item does not require payment.')
        if data['purpose']=='donation' and config and not config.donations_enabled:return Response({'error':'Donation registration is currently closed.'},status=503)
        email=data['email'].strip().lower()
        with transaction.atomic():
            donor,_=Donor.objects.get_or_create(email=email,defaults={k:data[k] for k in ['first_name','last_name','phone','country']})
            Donor.objects.select_for_update().get(pk=donor.pk)
            order=PaymentOrder.objects.select_for_update().filter(request_id=data['request_id']).first()
            if order:
                if order.donor_id!=donor.pk or (data['purpose'] in ['course','bundle'] and order.buyer_id!=request.user.pk) or (order.subtotal or order.amount)!=amount or order.purpose!=data['purpose'] or order.reference!=data['reference'] or order.discount_code!=normalize_code(data['discount_code']):
                    return Response({'error':'This request has already been used. Start a new payment request.'},status=409)
                if order.discount_id and order.discount.allowed_user_id and (not request.user.is_authenticated or order.discount.allowed_user_id!=request.user.pk):
                    raise serializers.ValidationError('Sign in with the eligible account to resume this discount.')
            else:
                courses=[]
                if data['purpose'] in ['course','bundle']:
                    from learning.services import purchase_courses
                    from learning.models import Enrollment
                    courses=purchase_courses(data['purpose'],data['reference'])
                    if Enrollment.objects.filter(user=request.user,course__in=courses,active=False).exists():
                        raise serializers.ValidationError('Your course access is inactive. Contact Recitera before purchasing again.')
                    if all(Enrollment.objects.filter(user=request.user,course=course,active=True).exists() for course in courses):
                        raise serializers.ValidationError('These courses are already in your library.')
                quote=calculate_discount(data['discount_code'],[product_line(data['purpose'],data['reference'],amount)],request.user,lock=True)
                order,created=PaymentOrder.objects.get_or_create(request_id=data['request_id'],defaults={'donor':donor,'buyer':request.user if data['purpose'] in ['course','bundle'] else None,'first_name':data['first_name'],'last_name':data['last_name'],'phone':data['phone'],'country':data['country'],'purpose':data['purpose'],'reference':data['reference'],'title':title,'amount':quote.total,'subtotal':quote.subtotal,'discount_amount':quote.discount,'discount_code':quote.code,'discount':quote.coupon,'comment':data['comment'],'anonymous':data['anonymous'],'mode':config.mode if config else 'test'})
                if not created and (order.donor_id!=donor.pk or (data['purpose'] in ['course','bundle'] and order.buyer_id!=request.user.pk) or (order.subtotal or order.amount)!=amount or order.purpose!=data['purpose'] or order.reference!=data['reference'] or order.discount_code!=quote.code):
                    return Response({'error':'This request has already been used. Start a new payment request.'},status=409)
                if created and courses:
                    from learning.services import snapshot_purchase
                    snapshot_purchase(order,courses)
                if created and order.amount==0:
                    order.status='paid';order.mode='free';order.paid_at=timezone.now();order.save(update_fields=['status','mode','paid_at'])
                    from learning.services import grant_order_access
                    grant_order_access(order)
        if order.status=='paid':return Response({'success':True,'order_id':str(order.id),'status':'paid'})
        if not ready(config):return Response({'success':True,'order_id':str(order.id),'status':order.status,'payment_ready':False},status=202)
        if order.mode!=config.mode:return Response({'error':'Payment settings changed. Please start a new request.'},status=409)
        if order.checkout_url:
            if order.checkout_expires_at and order.checkout_expires_at<=timezone.now():return Response({'error':'This checkout expired. Please start a new payment request.'},status=409)
            return Response({'success':True,'order_id':str(order.id),'checkout_url':order.checkout_url,'payment_ready':True})
        if not valid_origin(config.frontend_origin):return Response({'error':'Payment return address is not configured.'},status=503)
        origin=config.frontend_origin.rstrip('/')
        try:
            session=client(config).v1.checkout.sessions.create({'mode':'payment','customer_email':email,'client_reference_id':str(order.id),'metadata':{'order_id':str(order.id),'purpose':order.purpose},'line_items':[{'price_data':{'currency':'cad','unit_amount':int(order.amount*100),'product_data':{'name':order.title}},'quantity':1}],'success_url':f'{origin}/payments/result?order={order.id}','cancel_url':f'{origin}/payments/result?order={order.id}&cancelled=1'},{'idempotency_key':f'recitera-{order.id}'})
            if not session.url or not session.url.startswith('https://checkout.stripe.com/') or bool(session.livemode)!=(config.mode=='live'):raise ValueError('Unexpected checkout response')
            PaymentOrder.objects.filter(pk=order.pk).update(stripe_session_id=session.id,checkout_url=session.url,checkout_expires_at=datetime.fromtimestamp(session.expires_at,dt_timezone.utc),status='pending')
            return Response({'success':True,'order_id':str(order.id),'checkout_url':session.url,'payment_ready':True})
        except (stripe.StripeError,ValueError):return Response({'error':'Payment checkout is temporarily unavailable. No payment has been taken.'},status=503)

class PaymentStatus(APIView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request,order_id):
        order=PaymentOrder.objects.filter(pk=order_id).first()
        if not order:return Response({'error':'Not found'},status=404)
        return Response({'status':order.status,'amount':str(order.amount),'currency':order.currency,'purpose':order.purpose,'mode':order.mode,'subtotal':str(order.subtotal or order.amount),'discount_amount':str(order.discount_amount)},headers={'Cache-Control':'no-store'})

@csrf_exempt
@require_POST
def stripe_webhook(request):
    config=StripeSettings.objects.first()
    if not config:return JsonResponse({'error':'Webhook is not configured.'},status=503)
    event=None
    for mode in ['test','live']:
        _,secret=credentials(config,mode)
        if not secret:continue
        try:
            candidate=stripe.Webhook.construct_event(request.body,request.headers.get('Stripe-Signature',''),secret).to_dict()
            if bool(candidate.get('livemode'))!=(mode=='live'):continue
            event=candidate;break
        except (stripe.SignatureVerificationError,ValueError):continue
    if event is None:return JsonResponse({'error':'Invalid signature.'},status=400)
    accepted=['checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.async_payment_failed','checkout.session.expired']
    if event['type'] not in accepted:return JsonResponse({'received':True})
    from academy.services import process_event
    booking_result=process_event(event)
    if booking_result is not None:
        payload,status=booking_result
        if status==200:
            from academy.notifications import flush_mail
            flush_mail(limit=20,order_id=event['data']['object'].get('metadata',{}).get('academy_order_id'))
        return JsonResponse(payload,status=status)
    obj=event['data']['object'];order_id=obj.get('metadata',{}).get('order_id')
    if not order_id:return JsonResponse({'received':True})
    try:
        with transaction.atomic():
            if StripeEvent.objects.filter(event_id=event['id']).exists():return JsonResponse({'received':True})
            order=PaymentOrder.objects.select_for_update().filter(pk=order_id).first()
            if not order:return JsonResponse({'error':'Order not found.'},status=400)
            if (order.stripe_session_id and order.stripe_session_id!=obj['id']) or obj.get('amount_total')!=int(order.amount*100) or obj.get('currency')!='cad' or bool(event['livemode'])!=(order.mode=='live'):return JsonResponse({'error':'Payment does not match order.'},status=400)
            if event['type'] in ['checkout.session.completed','checkout.session.async_payment_succeeded'] and obj.get('payment_status')=='paid':
                order.status='paid';order.paid_at=timezone.now();order.stripe_payment_intent=obj.get('payment_intent') or '';order.stripe_session_id=obj['id'];order.save()
                from learning.services import grant_order_access
                grant_order_access(order)
            elif order.status!='paid' and event['type'] in ['checkout.session.async_payment_failed','checkout.session.expired']:
                order.status='failed' if event['type'].endswith('failed') else 'expired';order.save(update_fields=['status'])
            StripeEvent.objects.create(event_id=event['id'],event_type=event['type'])
    except (ValueError,serializers.ValidationError):return JsonResponse({'error':'Invalid event.'},status=400)
    return JsonResponse({'received':True})
