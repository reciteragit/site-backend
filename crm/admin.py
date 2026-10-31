import uuid
from urllib.parse import quote
from zoneinfo import available_timezones
from django import forms
from django.contrib import admin,messages
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin,TabularInline
from .models import Lead,LeadEvent,LeadNote,TrialRequest,TrialRecord,Communication
from .services import event,record_outcome


class LeadForm(forms.ModelForm):
    timezone=forms.ChoiceField(choices=[(name,name) for name in sorted(available_timezones())])
    class Meta:model=Lead;fields='__all__'
    def clean(self):
        data=super().clean()
        if data.get('stage')=='dropped' and not data.get('drop_reason'):self.add_error('drop_reason','Record why the lead is not continuing.')
        return data


class NoteInline(TabularInline):
    model=LeadNote;extra=0
    fields=['text','author','created_at'];readonly_fields=['author','created_at']
    def has_delete_permission(self,request,obj=None):return False


class EventInline(TabularInline):
    model=LeadEvent;extra=0
    fields=['kind','description','actor','created_at'];readonly_fields=fields
    def has_add_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False


class TrialInline(TabularInline):
    model=TrialRecord;extra=0
    fields=['booking','outcome','assessed_level','feedback_rating','interest'];readonly_fields=fields
    show_change_link=True
    def has_add_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False


class TrialTeacherFilter(admin.SimpleListFilter):
    title='Trial teacher';parameter_name='trial_teacher'
    def lookups(self,request,model_admin):
        from catalog.models import Teacher
        return [(str(row.pk),row.name) for row in Teacher.objects.all()]
    def queryset(self,request,queryset):
        if self.value():
            if not self.value().isdigit():return queryset.none()
            return queryset.filter(pk__in=TrialRecord.objects.filter(booking__slot__teacher__teacher_id=self.value()).values('lead_id'))
        return queryset


@admin.register(Lead)
class LeadAdmin(ModelAdmin):
    form=LeadForm
    change_list_template='admin/crm/lead_change_list.html'
    list_display=['name','email','stage','source','owner','preferred_teacher','campaign','follow_up_at','do_not_contact','updated_at']
    list_filter=['stage','source','owner',TrialTeacherFilter,'campaign','language','do_not_contact',('follow_up_at',admin.DateFieldListFilter)]
    search_fields=['name','email','whatsapp','goals','drop_reason']
    date_hierarchy='created_at'
    autocomplete_fields=['owner','preferred_teacher']
    readonly_fields=['key','source','user','trial_request','scholarship','created_at','updated_at','contact_actions','account_history']
    fieldsets=(('Contact',{'fields':('name','email','whatsapp','timezone','language','goals','contact_actions')}),('Lifecycle & ownership',{'fields':('stage','owner','preferred_teacher','follow_up_at','campaign','do_not_contact','drop_reason')}),('Source & connected account',{'fields':('source','user','trial_request','scholarship','account_history','key','created_at','updated_at')}))
    inlines=[TrialInline,NoteInline,EventInline]
    def get_queryset(self,request):return super().get_queryset(request).filter(merged_into__isnull=True).select_related('user','owner','preferred_teacher')
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
    @admin.display(description='Contact actions')
    def contact_actions(self,obj):
        digits=''.join(char for char in obj.whatsapp if char.isascii() and char.isdigit())
        if digits.startswith('00'):digits=digits[2:]
        if 6<=len(digits)<=15:return format_html('<a href="mailto:{}">Email contact</a> · <a href="https://wa.me/{}" target="_blank" rel="noopener noreferrer">Open WhatsApp</a>',quote(obj.email,safe='@'),digits)
        return format_html('<a href="mailto:{}">Email contact</a>',quote(obj.email,safe='@'))
    @admin.display(description='Account & booking history')
    def account_history(self,obj):
        if not obj.user_id:return 'Not connected to an authenticated account. Email-verified trial links connect requests without guessing ownership.'
        return format_html('<a href="{}?student__id__exact={}">View class booking history</a>',reverse('admin:academy_booking_changelist'),obj.user_id)
    def save_model(self,request,obj,form,change):
        previous=Lead.objects.get(pk=obj.pk).stage if change else None
        super().save_model(request,obj,form,change)
        if previous!=obj.stage:event(obj,'manual:'+uuid.uuid4().hex,'manual_stage',str(previous)+' → '+obj.stage,request.user)
    def save_formset(self,request,form,formset,change):
        for instance in formset.save(commit=False):
            if isinstance(instance,LeadNote) and not instance.pk:instance.author=request.user
            instance.save()
        formset.save_m2m()
    def changelist_view(self,request,extra_context=None):
        response=super().changelist_view(request,extra_context)
        if getattr(response,'context_data',None) and 'cl' in response.context_data:
            rows=response.context_data['cl'].queryset
            trial_contacts=rows.filter(pk__in=TrialRecord.objects.values('lead_id'))
            from academy.models import Booking
            from catalog.payment_models import PaymentOrder
            from django.db.models import Q
            paid_classes=Booking.objects.filter(status='confirmed',slot__kind='class',order__status='paid',order__mode='live',amount__gt=0).values('student_id')
            paid_courses=PaymentOrder.objects.filter(purpose__in=['course','bundle'],status='paid',mode='live',amount__gt=0).values('buyer_id')
            denominator=trial_contacts.count();converted=trial_contacts.filter(Q(user_id__in=paid_classes)|Q(user_id__in=paid_courses)).count()
            response.context_data['crm_metrics']={'active':rows.exclude(stage__in=['converted','dropped']).count(),'trial_contacts':denominator,'converted':converted,'conversion':round(converted/denominator*100,1) if denominator else 0,'due':rows.filter(follow_up_at__lte=timezone.now()).exclude(stage__in=['converted','dropped']).count()}
        return response


class TrialRecordForm(forms.ModelForm):
    class Meta:model=TrialRecord;fields='__all__'
    def clean(self):
        data=super().clean();outcome=data.get('outcome')
        if outcome in ['attended','no_show'] and self.instance.booking.slot.ends_at>timezone.now():raise forms.ValidationError('Report attendance after the trial ends.')
        if outcome=='cancelled' and self.instance.booking.status!='cancelled':raise forms.ValidationError('Use the booking cancellation approval workflow to cancel a class.')
        if outcome=='scheduled' and self.instance.outcome!='scheduled':raise forms.ValidationError('A recorded outcome cannot be reset to scheduled.')
        return data


@admin.register(TrialRecord)
class TrialRecordAdmin(ModelAdmin):
    form=TrialRecordForm
    list_display=['booking','lead','outcome','assessed_level','feedback_rating','interest','feedback_at']
    list_filter=['outcome','interest','booking__slot__teacher']
    search_fields=['lead__name','lead__email','teacher_notes','feedback']
    readonly_fields=['booking','lead','teacher_reported_at','feedback_rating','feedback','interest','feedback_at']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
    def save_model(self,request,obj,form,change):
        if obj.outcome in ['attended','no_show']:record_outcome(obj,obj.outcome,obj.assessed_level,obj.teacher_notes,request.user)
        else:super().save_model(request,obj,form,change)


@admin.register(Communication)
class CommunicationAdmin(ModelAdmin):
    list_display=['lead','recipient','kind','channel','due_at','sent_at','suppressed_at','attempts','last_error']
    list_filter=['kind','channel',('sent_at',admin.EmptyFieldListFilter),('suppressed_at',admin.EmptyFieldListFilter)]
    search_fields=['recipient','lead__name','lead__email']
    readonly_fields=[field.name for field in Communication._meta.fields]
    actions=['retry']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
    @admin.action(description='Requeue failed, unsent emails',permissions=['change'])
    def retry(self,request,queryset):
        count=queryset.filter(sent_at__isnull=True,suppressed_at__isnull=True).update(leased_until=None,last_error='',due_at=timezone.now())
        self.message_user(request,f'{count} unsent emails requeued. Suppressed contacts and already sent messages are unchanged.',messages.SUCCESS)


@admin.register(TrialRequest)
class TrialRequestAdmin(ModelAdmin):
    list_display=['name','email','language','campaign','created_at'];search_fields=['name','email'];list_filter=['language','campaign']
    readonly_fields=[field.name for field in TrialRequest._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
