"""Read-only operations dashboard. Every metric follows its ModelAdmin permissions."""
from collections import defaultdict
from datetime import timedelta, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.contrib import admin
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from academy.models import Booking, Order, EmailDelivery, TeachingProfile
from catalog.models import Teacher, TeacherApplication, ScholarshipApplication
from catalog.payment_models import PaymentOrder
from .admin_ui import permitted


def url(model, **query):
    from urllib.parse import urlencode
    target = reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_changelist')
    return target + ('?'+urlencode(query) if query else '')


def badge(status):
    return {'confirmed':'success','paid':'success','held':'warning','pending':'warning','payment_review':'danger','failed':'danger','expired':'neutral'}.get(status,'neutral')


def dashboard(request, context):
    try:
        days = int(request.GET.get('period',30))
    except (TypeError, ValueError):
        days = 30
    if days not in (7,30,90):
        days = 30
    try:
        zone = ZoneInfo(request.user.academy_profile.timezone)
    except (AttributeError, ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo('UTC')
    now = timezone.now()
    since = now-timedelta(days=days)
    local_today = now.astimezone(zone).date()
    view = lambda model:permitted(request,model._meta.label)
    metrics, attention, actions, revenue = [], [], [], defaultdict(lambda:Decimal('0'))
    for model in (Order, PaymentOrder):
        if view(model):
            for row in model.objects.filter(status='paid',mode='live',paid_at__gte=since).values('currency').annotate(total=Sum('amount')):
                revenue[row['currency']] += row['total']
    if view(Order) or view(PaymentOrder):
        amounts = ' · '.join(f'{value:,.2f} {currency}' for currency,value in sorted(revenue.items())) or '0.00 CAD'
        metrics.append({'label':'Payments received','value':amounts,'detail':f'Paid live orders · last {days} days','icon':'payments','url':url(Order if view(Order) else PaymentOrder,status__exact='paid',mode__exact='live',paid_at__gte=since.isoformat())})
    if view(Booking):
        count = Booking.objects.filter(status='confirmed',slot__starts_at__gte=now,slot__starts_at__lt=now+timedelta(days=7)).count()
        metrics.append({'label':'Upcoming classes','value':count,'detail':'Confirmed · next 7 days','icon':'calendar_month','url':url(Booking,status__exact='confirmed',slot__starts_at__gte=now.isoformat(),slot__starts_at__lt=(now+timedelta(days=7)).isoformat())})
    if view(Teacher):
        metrics.append({'label':'Published teachers','value':Teacher.objects.filter(published=True).count(),'detail':'Visible in the teacher directory','icon':'school','url':url(Teacher,published__exact=1)})
    if view(TeacherApplication):
        count=TeacherApplication.objects.filter(reviewed=False).count()
        metrics.append({'label':'Teacher applications','value':count,'detail':'Awaiting your review','icon':'person_add','url':url(TeacherApplication,reviewed__exact=0)})
        attention.append({'title':'Review teacher applications','count':count,'url':url(TeacherApplication,reviewed__exact=0),'icon':'person_add','detail':'New teachers waiting to hear from us'})
    if view(TeachingProfile):
        attention.append({'title':'Approve teaching accounts','count':TeachingProfile.objects.filter(approved=False).count(),'url':url(TeachingProfile,approved__exact=0),'icon':'verified_user','detail':'Check their profile and classroom link'})
    if view(EmailDelivery):
        attention.append({'title':'Unsent class confirmations','count':EmailDelivery.objects.filter(sent_at__isnull=True).count(),'url':url(EmailDelivery,sent_at__isnull=True),'icon':'outgoing_mail','detail':'Review delivery status and retry if needed'})
    if view(Order):
        attention.append({'title':'Payments needing review','count':Order.objects.filter(status='payment_review').count(),'url':url(Order,status__exact='payment_review'),'icon':'credit_card','detail':'Check the payment and booking before acting'})
    if view(ScholarshipApplication):
        attention.append({'title':'Scholarship requests','count':ScholarshipApplication.objects.filter(reviewed=False).count(),'url':url(ScholarshipApplication,reviewed__exact=0),'icon':'volunteer_activism','detail':'Help a learner take their next step'})
    for model,title,icon in [(Teacher,'Add a teacher','person_add'),(TeachingProfile,'Connect a classroom','video_camera_front')]:
        model_admin=admin.site._registry[model]
        if view(model) and model_admin.has_add_permission(request):
            actions.append({'title':title,'icon':icon,'url':reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_add')})
    bookings, activity, applications = [], [], []
    if view(Booking):
        rows=Booking.objects.filter(status__in=['confirmed','held','payment_review'],slot__starts_at__gt=now).select_related('student','slot').order_by('slot__starts_at')[:6]
        for row in rows:
            bookings.append({'teacher':row.teacher_name,'student':row.student.get_full_name() or row.student.email,'starts_at':row.slot.starts_at.astimezone(zone),'kind':'Free trial' if row.slot.kind=='trial' else 'Quran class','status':row.status.replace('_',' ').title(),'badge':badge(row.status),'url':reverse('admin:academy_booking_change',args=[row.pk])})
        start=local_today-timedelta(days=6)
        counts={row['day']:row['count'] for row in Booking.objects.filter(status='confirmed',slot__starts_at__gte=datetime.combine(start,time.min,tzinfo=zone),slot__starts_at__lte=now).annotate(day=TruncDate('slot__starts_at',tzinfo=zone)).values('day').annotate(count=Count('id'))}
        values=[counts.get(start+timedelta(days=i),0) for i in range(7)]
        peak=max(values,default=0) or 1
        activity=[{'label':(start+timedelta(days=i)).strftime('%a'),'date':start+timedelta(days=i),'count':value,'height':round(value/peak*100)} for i,value in enumerate(values)]
    if view(TeacherApplication):
        applications=[{'name':str(row),'date':row.created_at.astimezone(zone),'url':reverse('admin:catalog_teacherapplication_change',args=[row.pk])} for row in TeacherApplication.objects.filter(reviewed=False).order_by('-created_at')[:4]]
    context.update({'title':'Overview','dashboard':{'days':days,'periods':[7,30,90],'now':now.astimezone(zone),'zone':str(zone),'metrics':metrics,'attention':attention,'actions':actions,'bookings':bookings,'can_view_bookings':view(Booking),'bookings_url':url(Booking) if view(Booking) else '', 'activity':activity,'applications':applications,'can_view_applications':view(TeacherApplication),'applications_url':url(TeacherApplication) if view(TeacherApplication) else ''}})
    return context
