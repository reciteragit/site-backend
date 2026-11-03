from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from academy.models import Booking,Order,CancellationRequest
from catalog.models import TeacherApplication,VolunteerApplication,NewsletterSubscriber,ScholarshipApplication
from catalog.payment_models import PaymentOrder
from crm.models import TrialRequest,Lead,LeadEvent
from .outbox import queue


def link(app,model,pk):return f'/admin/{app}/{model}/{pk}/change/'


@receiver(post_save,sender=TrialRequest)
@receiver(post_save,sender=ScholarshipApplication)
@receiver(post_save,sender=TeacherApplication)
@receiver(post_save,sender=VolunteerApplication)
@receiver(post_save,sender=NewsletterSubscriber)
def form_created(sender,instance,created,raw=False,**kwargs):
    if raw or not created:return
    app=sender._meta.app_label;model=sender._meta.model_name
    name=getattr(instance,'name','') or getattr(instance,'full_name','') or getattr(instance,'first_name','')
    queue(f'form:{app}:{model}:{instance.pk}','forms',sender._meta.verbose_name.title()+' received',{'Record':instance.pk},link(app,model,instance.pk),{'Name':name,'Email':instance.email,'Phone':getattr(instance,'whatsapp','')})


@receiver(post_save,sender=Lead)
def lead_created(sender,instance,created,raw=False,**kwargs):
    if raw or not created:return
    queue('lead:'+str(instance.pk),'crm','CRM lead created',{'Lead':instance.pk,'Source':instance.source,'Stage':instance.stage},link('crm','lead',instance.pk),{'Name':instance.name,'Email':instance.email,'Phone':instance.whatsapp})


@receiver(post_save,sender=LeadEvent)
def lead_event(sender,instance,created,raw=False,**kwargs):
    if raw or not created or instance.kind not in ['stage','manual_stage','trial_outcome','trial_feedback','request_connected']:return
    queue('crm-event:'+str(instance.pk),'crm','CRM '+instance.kind.replace('_',' '),{'Lead':instance.lead_id,'Event':instance.kind,'Stage':instance.lead.stage},link('crm','lead',instance.lead_id))


@receiver(post_save,sender=Booking)
@receiver(post_save,sender=Order)
@receiver(post_save,sender=PaymentOrder)
@receiver(post_save,sender=CancellationRequest)
def booking_or_payment(sender,instance,raw=False,**kwargs):
    if raw:return
    app=sender._meta.app_label;model=sender._meta.model_name
    status=instance.status
    category='payments' if sender in [Order,PaymentOrder] else 'bookings'
    details={'Reference':instance.pk,'Status':status}
    if hasattr(instance,'amount'):details['Amount']=str(instance.amount)+' '+getattr(instance,'currency','CAD')
    if hasattr(instance,'mode'):details['Mode']=instance.mode
    if sender==PaymentOrder:details['Purpose']=instance.purpose
    if sender==CancellationRequest:details['Booking']=instance.booking_id
    if sender==Booking:details['Teacher']=instance.teacher_name;details['Class starts']=instance.slot.starts_at;details['Session']=instance.slot.kind
    queue(f'{app}:{model}:{instance.pk}:{status}',category,sender._meta.verbose_name.title()+' · '+status,details,link(app,model,instance.pk))


@receiver(post_save,sender=get_user_model())
def account_created(sender,instance,created,raw=False,**kwargs):
    if not raw and created:queue('account:'+str(instance.pk),'accounts','Account created',{'Account':instance.pk,'Staff':instance.is_staff},link('auth','user',instance.pk),{'Name':instance.get_full_name(),'Email':instance.email})


from django.contrib.admin.models import LogEntry
@receiver(post_save,sender=LogEntry)
def admin_action(sender,instance,created,raw=False,**kwargs):
    if raw or not created:return
    model=instance.content_type
    queue('admin:'+str(instance.pk),'admin','Administrator action',{'Action':{1:'add',2:'change',3:'delete'}.get(instance.action_flag,'action'),'Model':(str(model.app_label)+'.'+str(model.model)) if model else 'unknown','Record':instance.object_id,'Administrator account':instance.user_id})
