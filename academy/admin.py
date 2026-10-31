from config.admin_badges import status_badge
from unfold.admin import ModelAdmin, TabularInline
from django import forms
from django.contrib import admin, messages
from .models import TeachingProfile, Slot, Order, Booking, EmailDelivery, Profile
from .services import valid_meeting
from .timezones import zone
from .notifications import deliver
from rest_framework.exceptions import ValidationError


class TeacherForm(forms.ModelForm):
    class Meta:model=TeachingProfile;fields='__all__'
    def clean(self):
        data=super().clean()
        try:zone(data.get('timezone'))
        except ValidationError:self.add_error('timezone','Enter a valid IANA time zone.')
        url=data.get('meeting_url','')
        if (url or data.get('approved')) and not valid_meeting(data.get('meeting_provider'),url):self.add_error('meeting_url','Use a valid HTTPS class link matching the selected provider: Zoom, Google Meet or lms.recitera.com.')
        return data


@admin.register(TeachingProfile)
class TeachingAdmin(ModelAdmin):
    list_per_page=25
    fieldsets=(
        ('Teacher account', {'fields':('teacher','user','approved')}),
        ('Classroom', {'fields':('timezone','meeting_provider','meeting_url'),'description':'Class links are shared with learners only after their booking is confirmed.'}),
        ('Teaching biography', {'fields':('biography',)}),
        ('Scheduling', {'fields':('weekly_availability',)}),
    )
    form=TeacherForm
    list_display=['teacher','user','timezone','approved','meeting_provider']
    search_fields=['teacher__name','user__email']
    list_filter=['approved','meeting_provider']
    readonly_fields=['weekly_availability']
    @admin.display(description='Weekly availability')
    def weekly_availability(self,obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if not obj or not obj.pk:return 'Save the teaching account first.'
        return format_html('<a href="{}?teacher__id__exact={}">Manage weekly schedules</a> · <a href="{}?teacher={}">Add schedule</a>',reverse('admin:academy_availabilityschedule_changelist'),obj.pk,reverse('admin:academy_availabilityschedule_add'),obj.pk)
    autocomplete_fields=['teacher','user']


@admin.register(Slot)
class SlotAdmin(ModelAdmin):
    list_per_page=50
    list_select_related=['teacher__teacher']
    search_fields=['teacher__teacher__name']
    date_hierarchy='starts_at'
    list_display=['teacher','starts_at','ends_at','active']
    list_filter=['teacher','active','kind']
    readonly_fields=['id','teacher','starts_at','ends_at','active','schedule','kind']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_per_page=25
    date_hierarchy='created_at'
    @admin.display(description='Status',ordering='status')
    def payment_status(self,obj):return status_badge(obj.status)
    list_display=['id','user','amount','mode','payment_status','created_at']
    list_filter=['status','mode']
    search_fields=['user__email','stripe_session_id','discount_code']
    readonly_fields=[field.name for field in Order._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


class BookingForm(forms.ModelForm):
    class Meta:model=Booking;fields='__all__'
    def clean_meeting_url(self):
        value=self.cleaned_data['meeting_url']
        if not any(valid_meeting(provider,value) for provider in ['meet','zoom','lms']):
            raise forms.ValidationError('Use a valid Zoom, Google Meet or lms.recitera.com HTTPS class link.')
        return value


@admin.register(Booking)
class BookingAdmin(ModelAdmin):
    list_per_page=25
    @admin.display(description='Class starts (UTC)',ordering='slot__starts_at')
    def class_start(self,obj):return obj.slot.starts_at
    @admin.display(description='Session')
    def kind_label(self,obj):return 'Free trial' if obj.slot.kind=='trial' else 'Paid class'
    @admin.display(description='Status',ordering='status')
    def booking_status(self,obj):return status_badge(obj.status)
    form=BookingForm
    list_display=['teacher_name','student','class_start','kind_label','booking_status']
    list_filter=['status',('slot__starts_at',admin.DateFieldListFilter)]
    list_select_related=['student','slot']
    search_fields=['student__email','teacher_name']
    readonly_fields=[field.name for field in Booking._meta.fields if field.name!='meeting_url']
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        if change and 'meeting_url' in form.changed_data and obj.status=='confirmed':
            from django.db import transaction
            from .notifications import flush_mail
            obj.emails.update(sent_at=None,last_error='',leased_until=None)
            transaction.on_commit(lambda:flush_mail(limit=2,order_id=obj.order_id))
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(EmailDelivery)
class EmailAdmin(ModelAdmin):
    list_per_page=25
    search_fields=['recipient','booking__teacher_name']
    list_filter=[('sent_at',admin.EmptyFieldListFilter)]
    list_select_related=['booking']
    list_display=['booking','recipient','sent_at','attempts','last_error']
    readonly_fields=[field.name for field in EmailDelivery._meta.fields]
    actions=['retry']
    @admin.action(description='Retry selected unsent booking confirmations')
    def retry(self,request,queryset):
        count=sum(deliver(pk) for pk in queryset.filter(sent_at__isnull=True).values_list('pk',flat=True)[:10])
        self.message_user(request,f'{count} emails sent. Unconfigured or failed deliveries remain queued.',messages.INFO)
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display=['user','timezone']
    readonly_fields=['user','timezone']
    def has_add_permission(self,request):return False


from .models import GoogleIdentity

@admin.register(GoogleIdentity)
class GoogleIdentityAdmin(ModelAdmin):
    list_display=['user','email','created_at']
    search_fields=['user__email','email']
    readonly_fields=[field.name for field in GoogleIdentity._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):
        return bool(obj and obj.user.has_usable_password() and super().has_delete_permission(request,obj))


# Keep Django authentication and permissions while applying the same form widgets.
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin, GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.models import Group
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

admin.site.unregister(get_user_model())
admin.site.unregister(Group)

@admin.register(get_user_model())
class ReciteraUserAdmin(DjangoUserAdmin, ModelAdmin):
    form=UserChangeForm
    add_form=UserCreationForm
    change_password_form=AdminPasswordChangeForm
    list_per_page=25

@admin.register(Group)
class ReciteraGroupAdmin(DjangoGroupAdmin, ModelAdmin):
    pass


from .models import BookingNotice, CancellationRequest


@admin.register(CancellationRequest)
class CancellationRequestAdmin(ModelAdmin):
    list_display=['booking','status','requested_at','decided_at']
    list_filter=['status']
    search_fields=['booking__student__email','booking__teacher_name']
    readonly_fields=[field.name for field in CancellationRequest._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(BookingNotice)
class BookingNoticeAdmin(ModelAdmin):
    list_display=['booking','recipient','kind','due_at','sent_at','attempts','last_error']
    list_filter=['kind','sent_at']
    search_fields=['recipient','booking__teacher_name']
    readonly_fields=[field.name for field in BookingNotice._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

# Register the protected weekly scheduling editor.
from . import schedule_admin
