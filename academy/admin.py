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
class TeachingAdmin(admin.ModelAdmin):
    form=TeacherForm
    list_display=['teacher','user','timezone','approved','meeting_provider']
    search_fields=['teacher__name','user__email']
    list_filter=['approved','meeting_provider']
    autocomplete_fields=['teacher','user']


@admin.register(Slot)
class SlotAdmin(admin.ModelAdmin):
    list_display=['teacher','starts_at','ends_at','active']
    list_filter=['teacher','active']
    readonly_fields=['id','teacher','starts_at','ends_at','active','schedule','kind']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display=['id','user','amount','mode','status','created_at']
    list_filter=['status','mode']
    search_fields=['user__email','stripe_session_id']
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
class BookingAdmin(admin.ModelAdmin):
    form=BookingForm
    list_display=['id','student','teacher_name','slot','status']
    list_filter=['status']
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
class EmailAdmin(admin.ModelAdmin):
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
class ProfileAdmin(admin.ModelAdmin):
    list_display=['user','timezone']
    readonly_fields=['user','timezone']
    def has_add_permission(self,request):return False


from .models import GoogleIdentity

@admin.register(GoogleIdentity)
class GoogleIdentityAdmin(admin.ModelAdmin):
    list_display=['user','email','created_at']
    search_fields=['user__email','email']
    readonly_fields=[field.name for field in GoogleIdentity._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):
        return bool(obj and obj.user.has_usable_password() and super().has_delete_permission(request,obj))
