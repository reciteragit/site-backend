import uuid
import logging
import re
from datetime import timedelta, datetime, timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlsplit
import stripe
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, IntegrityError
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from catalog.models import Teacher
from catalog.discounts import ProductLine, calculate_discount
from catalog.discount_models import normalize_code
from catalog.payment_models import StripeSettings
from catalog.stripe_gateway import ready, client, valid_origin
from rest_framework.throttling import AnonRateThrottle

class AcademyAuthThrottle(AnonRateThrottle):
    scope="academy_auth"
    rate="10/min"

class AcademyWriteThrottle(AnonRateThrottle):
    scope="academy_write"
    rate="20/min"
    def get_cache_key(self,request,view):
        identity=str(request.user.pk) if request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope":self.scope,"ident":identity}
from .authentication import AcademyAuthentication, issue_token
from .models import AvailabilitySchedule, Profile, TeachingProfile, Slot, CartItem, Order, Booking, AccessToken, EmailDelivery
from .timezones import zone, local_time
from .services import available_queryset, expire_holds, lock_teachers, valid_meeting, slot_price
from .notifications import calendar

User=get_user_model()

class AcademyView(APIView):
    authentication_classes=[AcademyAuthentication]
    permission_classes=[IsAuthenticated]
    def finalize_response(self,request,response,*args,**kwargs):
        response=super().finalize_response(request,response,*args,**kwargs)
        response['Cache-Control']='private, no-store'
        response['Vary']='Authorization'
        return response


def profile_data(user):
    profile,_=Profile.objects.get_or_create(user=user)
    teaching=TeachingProfile.objects.filter(user=user).select_related('teacher').first()
    return {'google_connected':hasattr(user,'google_identity'),'has_password':user.has_usable_password(),'id':user.pk,'email':user.email,'first_name':user.first_name,'last_name':user.last_name,'timezone':profile.timezone,'teacher':teacher_data(teaching,private=True) if teaching else None}


def teacher_data(profile,private=False):
    t=profile.teacher
    data={'slug':t.slug,'name':t.name,'biography':profile.biography or t.biography,'based_in':t.based_in,'specialities':t.specialities,'experience':t.experience,'languages':t.languages,'image':t.image,'price':str(t.price),'currency':t.currency,'timezone':profile.timezone,'approved':profile.approved,'published':t.published}
    if private: data.update(meeting_provider=profile.meeting_provider,meeting_configured=bool(profile.meeting_url),meeting_url=profile.meeting_url)
    return data


class RegistrationSerializer(serializers.Serializer):
    email=serializers.EmailField(max_length=150)
    password=serializers.CharField(min_length=8,max_length=128,trim_whitespace=False,write_only=True)
    first_name=serializers.CharField(max_length=100)
    last_name=serializers.CharField(max_length=100,allow_blank=True,default='')
    timezone=serializers.CharField(max_length=100)
    def validate_timezone(self,value): zone(value);return value
    def validate(self,data):
        data['email']=data['email'].lower().strip()
        try:validate_password(data['password'],User(username=data['email'],email=data['email'],first_name=data['first_name'],last_name=data['last_name']))
        except DjangoValidationError as error:raise serializers.ValidationError({'password':error.messages})
        return data


class Register(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[];throttle_classes=[AcademyAuthThrottle]
    def post(self,request):
        s=RegistrationSerializer(data=request.data);s.is_valid(raise_exception=True);data=s.validated_data
        try:
            with transaction.atomic():
                user=User.objects.create_user(username=data['email'],email=data['email'],password=data['password'],first_name=data['first_name'],last_name=data['last_name'])
                Profile.objects.create(user=user,timezone=data['timezone'])
                token=issue_token(user)
        except IntegrityError:return Response({'error':'This email cannot be registered. Try signing in.'},status=400)
        return Response({'token':token,'profile':profile_data(user)},status=201)


class Login(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[];throttle_classes=[AcademyAuthThrottle]
    def post(self,request):
        email=request.data.get('email','');password=request.data.get('password','')
        if not isinstance(email,str) or not isinstance(password,str) or len(email)>150 or len(password)>128:raise serializers.ValidationError('Invalid sign-in details.')
        user=authenticate(request=request,username=email.lower().strip(),password=password)
        if not user:return Response({'error':'Email or password is incorrect.'},status=401)
        return Response({'token':issue_token(user),'profile':profile_data(user)})


class Logout(AcademyView):
    def post(self,request):
        request.auth.delete()
        return Response({'success':True})


class Me(AcademyView):
    def get(self,request):return Response(profile_data(request.user))
    def patch(self,request):
        class Update(serializers.Serializer):
            first_name=serializers.CharField(max_length=100,required=False)
            last_name=serializers.CharField(max_length=100,allow_blank=True,required=False)
            timezone=serializers.CharField(max_length=100,required=False)
        s=Update(data=request.data);s.is_valid(raise_exception=True);data=s.validated_data
        if 'timezone' in data:zone(data['timezone'])
        with transaction.atomic():
            for key in ['first_name','last_name']:
                if key in data:setattr(request.user,key,data[key])
            request.user.save(update_fields=['first_name','last_name'])
            profile,_=Profile.objects.get_or_create(user=request.user)
            if 'timezone' in data:profile.timezone=data['timezone'];profile.save(update_fields=['timezone'])
        return Response(profile_data(request.user))


class Password(AcademyView):
    throttle_classes=[AcademyAuthThrottle]
    def post(self,request):
        old=request.data.get('current_password','');new=request.data.get('password','')
        if not isinstance(old,str) or not isinstance(new,str) or len(new)>128 or not request.user.check_password(old):raise serializers.ValidationError('Check your current password and try again.')
        try:validate_password(new,request.user)
        except DjangoValidationError as error:raise serializers.ValidationError({'password':error.messages})
        with transaction.atomic():
            request.user.set_password(new);request.user.save(update_fields=['password'])
            AccessToken.objects.filter(user=request.user).delete()
        return Response({'success':True,'signed_out':True})


class PublicTeacher(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request,slug):
        t=Teacher.objects.filter(slug=slug,published=True).first()
        if not t:raise NotFound('Teacher not found.')
        profile=TeachingProfile.objects.filter(teacher=t,user__is_active=True).first()
        if profile:data=teacher_data(profile)
        else:data={'slug':t.slug,'name':t.name,'experience':t.experience,'languages':t.languages,'image':t.image,'price':str(t.price),'currency':t.currency,'biography':t.biography,'based_in':t.based_in,'specialities':t.specialities,'timezone':'','approved':False,'published':True}
        data['booking_enabled']=bool(profile and profile.approved and valid_meeting(profile.meeting_provider,profile.meeting_url))
        config=StripeSettings.objects.first()
        data['payment_ready']=bool(config and config.lessons_enabled and ready(config))
        data['payment_mode']=config.mode if config else 'test'
        return Response(data)


def public_teacher_slots(slug):
    profile = TeachingProfile.objects.filter(teacher__slug=slug, teacher__published=True, approved=True, user__is_active=True).first()
    if not profile or not valid_meeting(profile.meeting_provider, profile.meeting_url):
        return Slot.objects.none()
    return available_queryset().filter(teacher=profile, starts_at__lt=timezone.now()+timedelta(days=180))


class PublicDates(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self, request, slug):
        expire_holds()
        tz = zone(request.query_params.get('timezone', 'UTC'))
        dates = sorted({start.astimezone(tz).date().isoformat() for start in public_teacher_slots(slug).values_list('starts_at', flat=True)})
        return Response({'dates': dates})


class PublicSlots(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request,slug):
        expire_holds()
        rows = public_teacher_slots(slug)
        if request.query_params.get('date'):
            class Query(serializers.Serializer):
                date = serializers.DateField()
                timezone = serializers.CharField(max_length=100, default='UTC')
            query = Query(data=request.query_params); query.is_valid(raise_exception=True)
            day = query.validated_data['date']; tz = zone(query.validated_data['timezone'])
            today = timezone.now().astimezone(tz).date()
            if day < today - timedelta(days=1) or day > today + timedelta(days=181):
                return Response([])
            start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
            end = datetime.combine(day+timedelta(days=1), datetime.min.time(), tzinfo=tz)
            rows = rows.filter(starts_at__gte=start, starts_at__lt=end)
        return Response([{'id':str(s.id),'starts_at':s.starts_at.isoformat(),'ends_at':s.ends_at.isoformat(),'kind':s.kind,'price':str(slot_price(s)),'currency':s.teacher.teacher.currency} for s in rows.select_related('teacher__teacher')[:500]])


class TeacherEditSerializer(serializers.Serializer):
    name=serializers.CharField(max_length=120)
    biography=serializers.CharField(max_length=10000,allow_blank=True,default='')
    based_in=serializers.CharField(max_length=100,allow_blank=True,required=False)
    specialities=serializers.ListField(child=serializers.CharField(max_length=150),max_length=12,required=False)
    experience=serializers.CharField(max_length=80)
    languages=serializers.ListField(child=serializers.CharField(max_length=50),min_length=1,max_length=12)
    image=serializers.CharField(max_length=500)
    price=serializers.DecimalField(max_digits=8,decimal_places=2,min_value=Decimal('1'),max_value=Decimal('10000'))
    timezone=serializers.CharField(max_length=100)
    def validate_timezone(self,value):zone(value);return value
    def validate_image(self,value):
        if value.startswith('/assets/') and '..' not in value:return value
        p=urlsplit(value)
        if p.scheme=='https' and p.hostname and not p.username and not p.password:return value
        raise serializers.ValidationError('Use an HTTPS image URL or a site /assets/ image.')


class MyTeacher(AcademyView):
    def get(self,request):
        p=TeachingProfile.objects.select_related('teacher').filter(user=request.user).first()
        return Response(teacher_data(p,True) if p else None)
    def post(self,request):
        s=TeacherEditSerializer(data=request.data);s.is_valid(raise_exception=True);data=dict(s.validated_data)
        with transaction.atomic():
            # Lock the account as well so concurrent profile creation cannot duplicate teachers.
            User.objects.select_for_update().get(pk=request.user.pk)
            profile=TeachingProfile.objects.select_for_update().select_related('teacher').filter(user=request.user).first()
            tz=data.pop('timezone');bio=data.pop('biography')
            if not profile:
                slug=f'{slugify(data["name"])[:45] or "teacher"}-{uuid.uuid4().hex[:10]}'
                teacher=Teacher.objects.create(slug=slug,profile_url='',published=False,currency='CAD',**data)
                profile=TeachingProfile.objects.create(user=request.user,teacher=teacher,timezone=tz,biography=bio)
            else:
                for key,value in data.items():setattr(profile.teacher,key,value)
                profile.teacher.save(update_fields=list(data))
                profile.timezone=tz;profile.biography=bio;profile.save(update_fields=['timezone','biography'])
        return Response(teacher_data(profile,True))


def my_teacher(user):
    p=TeachingProfile.objects.filter(user=user).first()
    if not p:raise PermissionDenied('Create your teacher profile first.')
    return p


class MyAvailability(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def get(self, request):
        from .availability import schedule_data
        profile = my_teacher(request.user)
        schedule = AvailabilitySchedule.objects.filter(teacher=profile,kind=request.query_params.get('kind','class')).first()
        return Response({'schedule': schedule_data(schedule) if schedule else None})

    def post(self, request):
        from .availability import ScheduleInput, save_schedule
        profile = my_teacher(request.user)
        serializer = ScheduleInput(data=request.data); serializer.is_valid(raise_exception=True)
        return Response(save_schedule(profile, dict(serializer.validated_data)))


class MySlots(AcademyView):
    def get(self,request):
        expire_holds();p=my_teacher(request.user)
        rows=Slot.objects.filter(teacher=p,active=True,starts_at__gt=timezone.now()-timedelta(days=1)).prefetch_related('bookings')[:5000]
        return Response([{'id':str(s.id),'starts_at':s.starts_at.isoformat(),'ends_at':s.ends_at.isoformat(),'active':s.active,'kind':s.kind,'status':next((b.status for b in s.bookings.all() if b.status in ['held','confirmed']), 'available' if s.active else 'removed')} for s in rows])
    def post(self,request):
        p=my_teacher(request.user)
        class Input(serializers.Serializer):
            starts_local=serializers.CharField(max_length=40)
            duration_minutes=serializers.IntegerField(min_value=15,max_value=180)
        s=Input(data=request.data);s.is_valid(raise_exception=True)
        with transaction.atomic():
            p=TeachingProfile.objects.select_for_update().get(pk=p.pk)
            start=local_time(s.validated_data['starts_local'],p.timezone)
            if start<timezone.now()+timedelta(hours=1) or start>timezone.now()+timedelta(days=180):raise serializers.ValidationError('Choose a class between one hour and 180 days from now.')
            end=start+timedelta(minutes=s.validated_data['duration_minutes'])
            if Slot.objects.filter(teacher=p,active=True,starts_at__lt=end,ends_at__gt=start).exists():return Response({'error':'This time overlaps an existing class slot.'},status=409)
            slot=Slot.objects.create(teacher=p,starts_at=start,ends_at=end)
        return Response({'id':str(slot.id)},status=201)
    def delete(self,request):
        p=my_teacher(request.user)
        with transaction.atomic():
            lock_teachers([p.pk])
            try:slot=Slot.objects.select_for_update().filter(pk=request.data.get('slot_id'),teacher=p).first()
            except (ValueError,DjangoValidationError):slot=None
            if not slot:raise NotFound('Slot not found.')
            if slot.bookings.filter(status__in=['held','confirmed']).exists():return Response({'error':'A reserved or confirmed time cannot be removed.'},status=409)
            slot.active=False;slot.save(update_fields=['active'])
        return Response({'success':True})


def cart_data(user):
    available=set(available_queryset().values_list('pk',flat=True))
    items=CartItem.objects.filter(user=user).select_related('slot__teacher__teacher')
    return [{'id':item.pk,'slot_id':str(item.slot_id),'teacher':item.slot.teacher.teacher.name,'teacher_slug':item.slot.teacher.teacher.slug,'starts_at':item.slot.starts_at.isoformat(),'ends_at':item.slot.ends_at.isoformat(),'kind':item.slot.kind,'price':str(slot_price(item.slot)),'currency':item.slot.teacher.teacher.currency,'available':item.slot_id in available and valid_meeting(item.slot.teacher.meeting_provider,item.slot.teacher.meeting_url)} for item in items]


class Cart(AcademyView):
    def get(self,request):expire_holds();return Response(cart_data(request.user))
    def post(self,request):
        class Input(serializers.Serializer):slot_id=serializers.UUIDField()
        s=Input(data=request.data);s.is_valid(raise_exception=True);expire_holds()
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            if CartItem.objects.filter(user=request.user).count()>=10:raise serializers.ValidationError('A cart may contain at most ten classes.')
            slot=available_queryset().select_related('teacher').filter(pk=s.validated_data['slot_id']).first()
            if not slot:return Response({'error':'This time is no longer available.'},status=409)
            if slot.teacher.user_id==request.user.pk:raise serializers.ValidationError('You cannot book your own class.')
            if not valid_meeting(slot.teacher.meeting_provider,slot.teacher.meeting_url):raise serializers.ValidationError('The teacher classroom has not been configured.')
            CartItem.objects.get_or_create(user=request.user,slot=slot)
        return Response(cart_data(request.user))
    def delete(self,request):
        class Input(serializers.Serializer):item_id=serializers.IntegerField(min_value=1)
        s=Input(data=request.data);s.is_valid(raise_exception=True)
        CartItem.objects.filter(user=request.user,pk=s.validated_data['item_id']).delete()
        return Response(cart_data(request.user))


def order_data(order):
    return {'id':str(order.pk),'request_id':str(order.request_id),'status':order.status,'amount':str(order.amount),'subtotal':str(order.subtotal or order.amount),'discount_amount':str(order.discount_amount),'discount_code':order.discount_code,'currency':order.currency,'mode':order.mode,'expires_at':order.expires_at.isoformat(),'checkout_url':order.checkout_url if order.status in ['held','pending'] and order.expires_at>timezone.now() else ''}


class CartQuote(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request):
        class Input(serializers.Serializer):
            discount_code=serializers.CharField(max_length=40,allow_blank=True,default='')
        serializer=Input(data=request.data);serializer.is_valid(raise_exception=True)
        items=list(CartItem.objects.filter(user=request.user).select_related('slot__teacher__teacher'))
        if not items or len(items)>10:raise serializers.ValidationError('Your cart must contain between one and ten classes.')
        lines=[ProductLine('teacher',i.slot.teacher.teacher_id,slot_price(i.slot)) for i in items]
        return Response(calculate_discount(serializer.validated_data['discount_code'],lines,request.user).data(),headers={'Cache-Control':'private, no-store'})


class Checkout(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request):
        class Input(serializers.Serializer):
            request_id=serializers.UUIDField()
            timezone=serializers.CharField(max_length=100)
            discount_code=serializers.CharField(max_length=40,allow_blank=True,default="")
        s=Input(data=request.data);s.is_valid(raise_exception=True);data=s.validated_data;zone(data['timezone'])
        config=StripeSettings.objects.first()
        expire_holds()
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            order=Order.objects.select_for_update().filter(request_id=data['request_id']).first()
            if order and order.user_id!=request.user.pk:return Response({'error':'This checkout request is already in use.'},status=409)
            if order and 'discount_code' in request.data and normalize_code(data['discount_code'])!=order.discount_code:
                return Response({'error':'This reservation already has a fixed discount. Resume it or wait until it expires before changing the code.'},status=409)
            if not order:
                if Order.objects.filter(user=request.user,status__in=['held','pending']).exists():return Response({'error':'You already have a pending checkout. Open it from your account before starting another.'},status=409)
                items=list(CartItem.objects.filter(user=request.user).select_related('slot__teacher__teacher'))
                if not items or len(items)>10:raise serializers.ValidationError('Your cart must contain between one and ten classes.')
                profiles=lock_teachers([i.slot.teacher_id for i in items])
                slot_ids=[i.slot_id for i in items]
                slots=list(available_queryset().select_for_update(of=('self',)).filter(pk__in=slot_ids).select_related('teacher__teacher'))
                if len(slots)!=len(items):return Response({'error':'A class in your cart was just reserved or is no longer available. Refresh your cart.'},status=409)
                # Do not let a learner buy overlapping classes with different teachers.
                for index,slot in enumerate(slots):
                    t=slot.teacher.teacher
                    if slot.teacher.user_id==request.user.pk or not valid_meeting(slot.teacher.meeting_provider,slot.teacher.meeting_url) or t.currency!='CAD' or (slot.kind!='trial' and t.price<1):raise serializers.ValidationError('A teacher is not ready to accept this booking.')
                    if any(other.starts_at<slot.ends_at and other.ends_at>slot.starts_at for other in slots[index+1:]) or Booking.objects.filter(student=request.user,status__in=['held','confirmed'],slot__starts_at__lt=slot.ends_at,slot__ends_at__gt=slot.starts_at).exists():return Response({'error':'You already have a class at this time.'},status=409)
                quote=calculate_discount(data['discount_code'],[ProductLine('teacher',slot.teacher.teacher_id,slot_price(slot)) for slot in slots],request.user,lock=True)
                amount=quote.total
                if amount and (not config or not config.lessons_enabled or not ready(config) or not valid_origin(config.frontend_origin)):
                    return Response({'error':'Class payments are not configured yet.'},status=503)
                order=Order.objects.create(request_id=data['request_id'],user=request.user,email=request.user.email,amount=amount,subtotal=quote.subtotal,discount_amount=quote.discount,discount_code=quote.code,discount=quote.coupon,mode=config.mode if amount else 'free',expires_at=timezone.now()+timedelta(minutes=66))
                for index,slot in enumerate(slots):Booking.objects.create(order=order,slot=slot,student=request.user,student_timezone=data['timezone'],teacher_timezone=slot.teacher.timezone,teacher_name=slot.teacher.teacher.name,original_amount=slot_price(slot),amount=quote.amounts[index],meeting_url=slot.teacher.meeting_url)
            if order.amount == 0 and order.status == 'held':
                from .notifications import queue_confirmation, flush_mail
                order.status='paid';order.paid_at=timezone.now();order.save(update_fields=['status','paid_at'])
                for booking in order.bookings.select_related('student','slot__teacher__user'):
                    booking.status='confirmed';booking.save(update_fields=['status']);queue_confirmation(booking)
                CartItem.objects.filter(user=request.user,slot_id__in=order.bookings.values_list('slot_id',flat=True)).delete()
                transaction.on_commit(lambda order_id=order.pk: flush_mail(order_id=order_id), robust=True)
            if order.status in ['paid','expired','failed','payment_review']:return Response(order_data(order))
            if not config or not config.lessons_enabled or not ready(config) or not valid_origin(config.frontend_origin):return Response({'error':'Class payments are not configured yet.'},status=503)
            if order.mode!=config.mode:return Response({'error':'Payment settings changed. Contact Recitera before retrying.'},status=409)
            if order.checkout_url:return Response(order_data(order))
        # The database hold is committed before calling Stripe. Retries use the same idempotency key.
        origin=config.frontend_origin.rstrip('/')
        session_expiry=int((order.expires_at-timedelta(minutes=5)).timestamp())
        try:
            bookings=list(order.bookings.select_related('slot'))
            from .checkout import create_session
            session=create_session(client(config),order,{'mode':'payment','customer_email':order.email,'client_reference_id':str(order.id),'metadata':{'academy_order_id':str(order.id)},'expires_at':session_expiry,'line_items':[{'price_data':{'currency':'cad','unit_amount':int(b.amount*100),'product_data':{'name':f'Class with {b.teacher_name} — {b.slot.starts_at.strftime("%Y-%m-%d %H:%M UTC")}'}},'quantity':1} for b in bookings if b.amount > 0],'success_url':f'{origin}/account?order={order.id}','cancel_url':f'{origin}/cart?order={order.id}&cancelled=1'})
            if not session.url or not session.url.startswith('https://checkout.stripe.com/') or bool(session.livemode)!=(order.mode=='live'):raise ValueError('Invalid Stripe session')
            with transaction.atomic():
                order=Order.objects.select_for_update().get(pk=order.pk)
                order.stripe_session_id=session.id;order.checkout_url=session.url
                if order.status=='held':order.status='pending'
                order.save(update_fields=['stripe_session_id','checkout_url','status'])
            return Response(order_data(order))
        except (stripe.StripeError,ValueError) as exc:
            logging.getLogger(__name__).warning('Academy checkout creation failed: type=%s code=%s param=%s', type(exc).__name__, getattr(exc,'code',None), getattr(exc,'param',None))
            if isinstance(exc, stripe.InvalidRequestError):
                logging.getLogger(__name__).warning('Checkout recovery rejection: %s',re.sub(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+','[email]',str(exc))[:600])
            if getattr(exc, 'param', None) == 'expires_at':
                return Response({'error':'This payment preparation window has ended. Your class remains reserved until the time shown above. After it expires, refresh the cart to start a new checkout.'},status=503)
            return Response({'error':'We could not confirm checkout creation. Your temporary reservation is retained; retry this same checkout or wait until it expires.'},status=503)


def booking_data(booking,viewer):
    row={'id':str(booking.id),'order_id':str(booking.order_id),'teacher':booking.teacher_name,'teacher_slug':booking.slot.teacher.teacher.slug,'starts_at':booking.slot.starts_at.isoformat(),'ends_at':booking.slot.ends_at.isoformat(),'timezone':booking.student_timezone,'status':booking.status,'kind':booking.slot.kind,'amount':str(booking.amount),'currency':'CAD','mode':booking.order.mode,'meeting_url':booking.meeting_url if booking.status=='confirmed' else '', 'email_status': 'sent' if booking.emails.filter(recipient=viewer.email,sent_at__isnull=False).exists() else 'queued' if booking.status=='confirmed' else 'not_sent'}
    from .calendar_links import calendar_links
    from .models import CancellationRequest
    cancellation=CancellationRequest.objects.filter(booking=booking).first()
    row['cancellation']={'status':cancellation.status,'reason':cancellation.reason,'requested_at':cancellation.requested_at.isoformat()} if cancellation else None
    row['can_request_cancellation']=booking.student_id==viewer.pk and booking.status=='confirmed' and not cancellation and booking.slot.starts_at>=timezone.now()+timedelta(hours=24)
    row['calendar_links']=calendar_links(booking) if booking.status=='confirmed' else {}
    trial=getattr(booking,'crm_trial',None)
    row['trial_feedback']={'outcome':trial.outcome,'feedback_submitted':bool(trial.feedback_at),'teacher_reported':bool(trial.teacher_reported_at),'can_submit':booking.status=='confirmed' and booking.slot.ends_at<=timezone.now()} if trial else None
    if booking.slot.teacher.user_id==viewer.pk:row.update(student_name=booking.student.get_full_name(),student_email=booking.student.email)
    return row


class MyBookings(AcademyView):
    def get(self,request):
        expire_holds()
        rows=Booking.objects.filter(student=request.user).select_related('slot__teacher__teacher','order','student').prefetch_related('emails').order_by('-slot__starts_at')[:200]
        return Response({'bookings':[booking_data(b,request.user) for b in rows],'orders':[order_data(o) for o in Order.objects.filter(user=request.user)[:50]]})


class TeachingBookings(AcademyView):
    def get(self,request):
        p=my_teacher(request.user)
        rows=Booking.objects.filter(slot__teacher=p,status__in=['confirmed','cancelled']).select_related('slot__teacher__teacher','order','student').prefetch_related('emails').order_by('slot__starts_at')[:200]
        return Response([booking_data(b,request.user) for b in rows])


class BookingCalendar(AcademyView):
    def get(self,request,booking_id):
        b=Booking.objects.select_related('slot__teacher','order').filter(pk=booking_id,status__in=['confirmed','cancelled']).first()
        if not b or (b.student_id!=request.user.pk and b.slot.teacher.user_id!=request.user.pk):raise NotFound('Booking not found.')
        response=HttpResponse(calendar(b),content_type='text/calendar; charset=utf-8')
        response['Content-Disposition']='attachment; filename="recitera-class.ics"'
        return response


class MailRetry(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request):
        from .notifications import deliver
        ids=EmailDelivery.objects.filter(booking__student=request.user,recipient=request.user.email,sent_at__isnull=True,booking__status='confirmed').values_list('pk',flat=True)[:2]
        return Response({'sent':sum(deliver(pk) for pk in ids)})


class ScheduledMail(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request):
        import os,hmac
        secret=os.getenv('CRON_SECRET','')
        from .workflow_auth import workflow_authorized
        authorization=request.headers.get('Authorization','')
        if not ((secret and hmac.compare_digest(authorization,f'Bearer {secret}')) or (authorization.startswith('Bearer ') and workflow_authorized(authorization[7:]))):raise PermissionDenied('Not authorized.')
        from .notifications import flush_mail
        expire_holds()
        from .booking_notices import flush_notices
        from crm.communications import flush as flush_crm
        return Response({'sent':flush_mail(5),'notices_sent':flush_notices(10),'crm_sent':flush_crm(5)})
