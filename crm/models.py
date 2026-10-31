import uuid
from django.conf import settings
from django.db import models


class TrialRequest(models.Model):
    request_id=models.UUIDField(unique=True,default=uuid.uuid4,editable=False)
    name=models.CharField(max_length=150)
    email=models.EmailField()
    whatsapp=models.CharField(max_length=40,blank=True)
    timezone=models.CharField(max_length=100,default='UTC')
    language=models.CharField(max_length=80,blank=True)
    goals=models.TextField(blank=True,max_length=2000)
    campaign=models.CharField(max_length=150,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self):return self.name


class Lead(models.Model):
    STAGES=[('new','New'),('assessment','Awaiting assessment'),('trial_booked','Trial booked'),('trial_completed','Trial completed'),('converted','Converted to student'),('dropped','Dropped / not continuing')]
    key=models.CharField(max_length=100,unique=True,editable=False)
    source=models.CharField(max_length=20,choices=[('trial_request','Trial request'),('trial_booking','Trial booking'),('scholarship','Scholarship')])
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='crm_leads')
    merged_into=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='merged_sources',editable=False)
    name=models.CharField(max_length=150)
    email=models.EmailField()
    whatsapp=models.CharField(max_length=40,blank=True)
    timezone=models.CharField(max_length=100,default='UTC')
    language=models.CharField(max_length=80,blank=True)
    goals=models.TextField(blank=True)
    campaign=models.CharField(max_length=150,blank=True)
    stage=models.CharField(max_length=20,choices=STAGES,default='new')
    owner=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='owned_crm_leads')
    preferred_teacher=models.ForeignKey('catalog.Teacher',on_delete=models.SET_NULL,null=True,blank=True)
    follow_up_at=models.DateTimeField(null=True,blank=True)
    do_not_contact=models.BooleanField(default=False)
    drop_reason=models.TextField(blank=True,max_length=2000)
    trial_request=models.OneToOneField(TrialRequest,on_delete=models.PROTECT,null=True,blank=True)
    scholarship=models.OneToOneField('catalog.ScholarshipApplication',on_delete=models.PROTECT,null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:ordering=['-updated_at']
    def __str__(self):return self.name or self.email


class LeadEvent(models.Model):
    lead=models.ForeignKey(Lead,on_delete=models.PROTECT,related_name='events')
    key=models.CharField(max_length=180,unique=True)
    kind=models.CharField(max_length=40)
    description=models.TextField(blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:ordering=['-created_at']


class LeadNote(models.Model):
    lead=models.ForeignKey(Lead,on_delete=models.PROTECT,related_name='notes')
    author=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,editable=False)
    text=models.TextField(max_length=5000)
    created_at=models.DateTimeField(auto_now_add=True)


class TrialRecord(models.Model):
    booking=models.OneToOneField('academy.Booking',on_delete=models.PROTECT,related_name='crm_trial')
    lead=models.ForeignKey(Lead,on_delete=models.PROTECT,related_name='trials')
    outcome=models.CharField(max_length=12,choices=[('scheduled','Scheduled'),('attended','Attended'),('no_show','No show'),('cancelled','Cancelled')],default='scheduled')
    assessed_level=models.CharField(max_length=200,blank=True)
    teacher_notes=models.TextField(max_length=5000,blank=True)
    teacher_reported_at=models.DateTimeField(null=True,blank=True)
    feedback_rating=models.PositiveSmallIntegerField(null=True,blank=True)
    feedback=models.TextField(max_length=3000,blank=True)
    interest=models.CharField(max_length=16,choices=[('','Not answered'),('continue','Continue learning'),('help','Need guidance'),('not_continue','Not continuing')],blank=True)
    feedback_at=models.DateTimeField(null=True,blank=True)


class Communication(models.Model):
    trial_request=models.ForeignKey(TrialRequest,on_delete=models.PROTECT,null=True,blank=True)
    lead=models.ForeignKey(Lead,on_delete=models.PROTECT,related_name='communications')
    booking=models.ForeignKey('academy.Booking',on_delete=models.PROTECT,null=True,blank=True)
    key=models.CharField(max_length=180,unique=True)
    kind=models.CharField(max_length=30,choices=[('trial_received','Trial request received'),('trial_followup','Trial follow-up')])
    channel=models.CharField(max_length=10,default='email',choices=[('email','Email')])
    recipient=models.EmailField()
    due_at=models.DateTimeField()
    sent_at=models.DateTimeField(null=True,blank=True)
    suppressed_at=models.DateTimeField(null=True,blank=True)
    attempts=models.PositiveIntegerField(default=0)
    leased_until=models.DateTimeField(null=True,blank=True)
    last_error=models.CharField(max_length=100,blank=True)
    class Meta:ordering=['due_at']
