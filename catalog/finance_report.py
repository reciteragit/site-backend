"""Read-only administrative reporting across class and catalog orders."""
import csv
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, available_timezones
from django import forms
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, F, Value, CharField, Count, Sum
from django.db.models.functions import Cast
from django.http import StreamingHttpResponse
from django.template.response import TemplateResponse
from django.utils import timezone
from academy.models import Order
from learning.models import CoursePurchase
from .models import Teacher, Course
from .payment_models import PaymentOrder


def finance_allowed(request):
    user=request.user
    return user.is_active and user.is_staff and all(user.has_perm(f'{app}.view_{model}') or user.has_perm(f'{app}.change_{model}') for app,model in [('academy','order'),('catalog','paymentorder')])


class FinanceFilters(forms.Form):
    start=forms.DateField(required=False,label='From date',widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(required=False,label='Through date',widget=forms.DateInput(attrs={'type':'date'}))
    timezone=forms.ChoiceField(choices=[(name,name) for name in sorted(available_timezones())],initial='UTC',label='Report time zone')
    date_basis=forms.ChoiceField(choices=[('created_at','Checkout created'),('paid_at','Payment confirmed')],initial='created_at')
    kind=forms.ChoiceField(required=False,label='Payment type',choices=[('','All payment types'),('class','Class bookings'),('course','Recorded courses'),('bundle','Course packages'),('donation','Donations'),('other','Other payments'),('lesson','Legacy lessons')])
    status=forms.ChoiceField(required=False,label='Payment status',choices=[('','All statuses')]+[(x,x.replace('_',' ').title()) for x in ['paid','held','pending','registered','payment_review','failed','expired']])
    mode=forms.ChoiceField(label='Payment mode',choices=[('live','Live only'),('all','All modes (separate totals)'),('test','Test only'),('free','Free checkouts')])
    currency=forms.CharField(required=False,max_length=3)
    teacher=forms.ModelChoiceField(queryset=Teacher.objects.all(),required=False,empty_label='All teachers')
    course=forms.ModelChoiceField(queryset=Course.objects.all(),required=False,empty_label='All courses')
    q=forms.CharField(required=False,max_length=200,label='Customer / email / payment reference')
    discount_code=forms.CharField(required=False,max_length=40)
    minimum=forms.DecimalField(required=False,min_value=0,max_digits=12,decimal_places=2,label='Minimum amount')
    maximum=forms.DecimalField(required=False,min_value=0,max_digits=12,decimal_places=2,label='Maximum amount')
    def clean_currency(self):
        value=self.cleaned_data['currency'].upper().strip()
        if value and (len(value)!=3 or not value.isascii() or not value.isalpha()):raise forms.ValidationError('Use a three-letter currency code such as CAD.')
        return value
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['end']<data['start']:raise forms.ValidationError('The end date must be on or after the start date.')
        if data.get('minimum') is not None and data.get('maximum') is not None and data['maximum']<data['minimum']:raise forms.ValidationError('Maximum amount must be at least the minimum.')
        return data


def filtered_orders(data):
    classes=Order.objects.all();payments=PaymentOrder.objects.all()
    zone=ZoneInfo(data['timezone']);field=data['date_basis']
    common={}
    if data.get('start'):common[field+'__gte']=timezone.make_aware(datetime.combine(data['start'],time.min),zone)
    if data.get('end'):common[field+'__lt']=timezone.make_aware(datetime.combine(data['end']+timedelta(days=1),time.min),zone)
    for key in ['status','currency']:
        if data.get(key):common[key]=data[key]
    if data['mode']!='all':common['mode']=data['mode']
    if data.get('minimum') is not None:common['amount__gte']=data['minimum']
    if data.get('maximum') is not None:common['amount__lte']=data['maximum']
    if data.get('discount_code'):common['discount_code__iexact']=data['discount_code'].strip()
    classes=classes.filter(**common);payments=payments.filter(**common)
    if data.get('kind'):
        if data['kind']=='class':payments=payments.none()
        else:classes=classes.none();payments=payments.filter(purpose=data['kind'])
    if data.get('teacher'):
        teacher=data['teacher']
        ids=Order.objects.filter(bookings__slot__teacher__teacher=teacher).values('pk')
        classes=classes.filter(pk__in=ids)
        course_ids=CoursePurchase.objects.filter(course__teacher=teacher).values('order_id')
        payments=payments.filter(Q(pk__in=course_ids)|Q(purpose='course',reference__in=Course.objects.filter(teacher=teacher).values('slug'))|Q(purpose='lesson',reference=teacher.slug))
    if data.get('course'):
        course=data['course'];classes=classes.none()
        payments=payments.filter(Q(pk__in=CoursePurchase.objects.filter(course=course).values('order_id'))|Q(purpose='course',reference=course.slug))
    if data.get('q'):
        query=data['q'].strip()
        classes=classes.annotate(search_id=Cast('id',CharField())).filter(Q(user__email__icontains=query)|Q(user__first_name__icontains=query)|Q(user__last_name__icontains=query)|Q(email__icontains=query)|Q(stripe_session_id__icontains=query)|Q(search_id__icontains=query))
        payments=payments.annotate(search_id=Cast('id',CharField())).filter(Q(donor__email__icontains=query)|Q(buyer__email__icontains=query)|Q(first_name__icontains=query)|Q(last_name__icontains=query)|Q(title__icontains=query)|Q(reference__icontains=query)|Q(stripe_session_id__icontains=query)|Q(search_id__icontains=query))
    return classes,payments


def normalized_orders(classes,payments):
    columns=['report_id','source','kind','title','customer_email','created_at','paid_at','amount','subtotal','discount_amount','discount_code','currency','mode','status']
    classes=classes.annotate(report_id=Cast('id',CharField()),source=Value('class'),kind=Value('class'),title=Value('Class booking',output_field=CharField()))
    # Both projections must use the same column names and order for UNION ALL.
    first=classes.annotate(customer_email=F('email')).order_by().values(*columns)
    second=payments.annotate(report_id=Cast('id',CharField()),source=Value('catalog'),kind=F('purpose'),customer_email=F('donor__email')).order_by().values(*columns)
    return first.union(second,all=True).order_by('-created_at','source','report_id')


def report_totals(querysets):
    totals={}
    for queryset in querysets:
        for group in queryset.order_by().values('currency','mode','status').annotate(count=Count('pk'),total=Sum('amount'),discount=Sum('discount_amount')):
            row=totals.setdefault((group['currency'],group['mode']),{'currency':group['currency'],'mode':group['mode'],'count':0,'paid_count':0,'paid':Decimal('0'),'pending':Decimal('0'),'saved':Decimal('0'),'review':Decimal('0'),'failed_count':0})
            row['count']+=group['count']
            if group['status']=='paid':row['paid']+=group['total'] or 0;row['saved']+=group['discount'] or 0;row['paid_count']+=group['count']
            elif group['status'] in ['held','pending','registered']:row['pending']+=group['total'] or 0
            elif group['status']=='payment_review':row['review']+=group['total'] or 0
            elif group['status'] in ['failed','expired']:row['failed_count']+=group['count']
    return [totals[key] for key in sorted(totals)]


class CSVBuffer:
    def write(self,value):return value


def csv_cell(value):
    value='' if value is None else str(value)
    # Spreadsheet software may execute formulas, including after whitespace/control characters.
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value


def finance_report(request,site):
    if not finance_allowed(request):raise PermissionDenied
    today=timezone.now().date()
    params=request.GET.copy()
    if not params:params.update({'start':(today-timedelta(days=29)).isoformat(),'end':today.isoformat()})
    for key,value in [('timezone','UTC'),('date_basis','created_at'),('mode','live')]:
        if key not in params:params[key]=value
    form=FinanceFilters(params)
    context={**site.each_context(request),'title':'Financial reports','form':form,'totals':[],'page':None,'count':0}
    if form.is_valid():
        classes,payments=filtered_orders(form.cleaned_data)
        rows=normalized_orders(classes,payments)
        if request.GET.get('format')=='csv':
            writer=csv.writer(CSVBuffer())
            def stream():
                yield '\ufeff'+writer.writerow(['Reference','Source','Type','Title','Customer email','Created UTC','Paid UTC','Subtotal','Discount','Discount code','Amount','Currency','Mode','Status'])
                for row in rows.iterator(chunk_size=500):
                    values=[row['report_id'],row['source'],row['kind'],row['title'],row['customer_email'],row['created_at'].isoformat(),row['paid_at'].isoformat() if row['paid_at'] else '',row['subtotal'] or row['amount'],row['discount_amount'],row['discount_code'],row['amount'],row['currency'],row['mode'],row['status']]
                    yield writer.writerow([csv_cell(value) for value in values])
            response=StreamingHttpResponse(stream(),content_type='text/csv; charset=utf-8')
            response['Content-Disposition']='attachment; filename="recitera-financial-report.csv"'
            response['Cache-Control']='private, no-store'
            return response
        paginator=Paginator(rows,50)
        page=paginator.get_page(request.GET.get('page'))
        context.update(totals=report_totals([classes,payments]),page=page,count=paginator.count,report_timezone=form.cleaned_data['timezone'])
        query=params.copy();query.pop('page',None);query.pop('format',None)
        context['filter_query']=query.urlencode()
    response=TemplateResponse(request,'admin/catalog/financial_report.html',context)
    response['Cache-Control']='private, no-store'
    return response
