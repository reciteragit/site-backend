from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from academy.models import Booking
from catalog.payment_models import PaymentOrder
from .models import Lead,LeadEvent,TrialRecord,Communication


def event(lead,key,kind,description='',actor=None):
    LeadEvent.objects.get_or_create(key=key,defaults={'lead':lead,'kind':kind,'description':description,'actor':actor})


def advance(lead,stage,key):
    ranks={'new':0,'assessment':1,'trial_booked':2,'trial_completed':3,'converted':4}
    if lead.stage in ['converted','dropped'] or ranks.get(stage,0)<=ranks.get(lead.stage,0):return
    previous=lead.stage;lead.stage=stage;lead.save(update_fields=['stage','updated_at'])
    event(lead,key,'stage',previous+' → '+stage)


def paying_student(user_id):
    return Booking.objects.filter(student_id=user_id,status='confirmed',slot__kind='class',order__status='paid',order__mode='live',amount__gt=0).exists() or PaymentOrder.objects.filter(buyer_id=user_id,purpose__in=['course','bundle'],status='paid',mode='live',amount__gt=0).exists()


def sync_request(request):
    with transaction.atomic():
        lead,_=Lead.objects.get_or_create(key='request:'+str(request.request_id),defaults={'source':'trial_request','trial_request':request,'name':request.name,'email':request.email,'whatsapp':request.whatsapp,'timezone':request.timezone,'language':request.language,'goals':request.goals,'campaign':request.campaign})
        event(lead,'request:'+str(request.request_id),'trial_request','Trial enquiry received')
        Communication.objects.get_or_create(key='request-received:'+str(request.request_id),defaults={'lead':lead,'kind':'trial_received','trial_request':request,'recipient':lead.email,'due_at':timezone.now()})
    return lead


def sync_scholarship(application):
    with transaction.atomic():
        lead,_=Lead.objects.get_or_create(key='scholarship:'+str(application.request_id),defaults={'source':'scholarship','scholarship':application,'name':application.name,'email':application.email,'whatsapp':application.whatsapp,'goals':application.message})
        event(lead,'scholarship:'+str(application.request_id),'scholarship','Scholarship / financial support requested')
    return lead


def sync_booking(booking):
    if booking.slot.kind!='trial' or booking.order.mode=='test' or booking.status not in ['confirmed','cancelled']:return
    with transaction.atomic():
        lead,_=Lead.objects.get_or_create(key='user:'+str(booking.student_id),defaults={'source':'trial_booking','user':booking.student,'name':booking.student.get_full_name() or booking.student.email,'email':booking.student.email,'timezone':booking.student_timezone,'preferred_teacher':booking.slot.teacher.teacher})
        lead=Lead.objects.select_for_update().get(pk=lead.pk)
        trial,_=TrialRecord.objects.get_or_create(booking=booking,defaults={'lead':lead})
        event(lead,'booking:'+str(booking.pk)+':'+booking.status,'trial_'+booking.status,'Trial with '+booking.teacher_name)
        if booking.status=='cancelled':
            trial.outcome='cancelled';trial.save(update_fields=['outcome'])
            Communication.objects.filter(booking=booking,kind='trial_followup',sent_at__isnull=True).update(suppressed_at=timezone.now())
            if lead.stage=='trial_booked' and not lead.trials.filter(booking__status='confirmed',booking__slot__starts_at__gt=timezone.now()).exists():
                lead.stage='assessment';lead.save(update_fields=['stage','updated_at'])
                event(lead,'cancelled-stage:'+str(booking.pk),'stage','Trial cancelled; awaiting reassessment')
        else:
            advance(lead,'trial_booked','stage-booked:'+str(booking.pk))
            # Backfill records without sending follow-ups for very old trials.
            due=booking.slot.ends_at+timedelta(hours=1)
            suppressed=timezone.now() if due<timezone.now()-timedelta(days=2) else None
            Communication.objects.get_or_create(key='followup:'+str(booking.pk),defaults={'lead':lead,'booking':booking,'kind':'trial_followup','recipient':booking.student.email,'due_at':due,'suppressed_at':suppressed})
        if paying_student(booking.student_id):advance(lead,'converted','paid-user:'+str(booking.student_id))
    return lead


def sync_conversion(user_id):
    if not user_id or not paying_student(user_id):return
    with transaction.atomic():
        for lead in Lead.objects.select_for_update().filter(user_id=user_id,merged_into__isnull=True):advance(lead,'converted','paid-lead:'+str(lead.pk))


def sync_sources(limit=200):
    from catalog.models import ScholarshipApplication
    rows=ScholarshipApplication.objects.filter(lead__isnull=True).order_by('pk')[:limit]
    for row in rows:sync_scholarship(row)
    bookings=Booking.objects.filter(slot__kind='trial',status__in=['confirmed','cancelled']).exclude(order__mode='test').filter(Q(crm_trial__isnull=True)|Q(status='cancelled',crm_trial__outcome='scheduled')).select_related('student','slot__teacher__teacher','order').order_by('pk')[:limit]
    for booking in bookings:sync_booking(booking)
    # Reconcile a payment and trial that committed concurrently in different workers.
    paid_classes=Booking.objects.filter(status='confirmed',slot__kind='class',order__status='paid',order__mode='live',amount__gt=0).values('student_id')
    paid_courses=PaymentOrder.objects.filter(purpose__in=['course','bundle'],status='paid',mode='live',amount__gt=0).values('buyer_id')
    candidates=Lead.objects.filter(merged_into__isnull=True).exclude(stage__in=['converted','dropped']).filter(Q(user_id__in=paid_classes)|Q(user_id__in=paid_courses)).order_by('pk')[:limit]
    for lead in candidates:sync_conversion(lead.user_id)


def record_outcome(record,outcome,level,notes,actor):
    record.outcome=outcome;record.assessed_level=level;record.teacher_notes=notes;record.teacher_reported_at=timezone.now();record.save(update_fields=['outcome','assessed_level','teacher_notes','teacher_reported_at'])
    if outcome=='attended':advance(record.lead,'trial_completed','attended:'+str(record.pk))
    event(record.lead,'outcome:'+str(record.pk)+':'+outcome,'trial_outcome',outcome,actor)


def claim_token(enquiry):
    from django.core.signing import TimestampSigner,b62_encode
    class EnquirySigner(TimestampSigner):
        def timestamp(self):return b62_encode(int(enquiry.created_at.timestamp()))
    return EnquirySigner(salt='recitera-crm-trial-claim').sign_object({'request_id':str(enquiry.request_id)})
