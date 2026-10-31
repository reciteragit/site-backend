import json
from zoneinfo import available_timezones
from django import forms
from django.contrib import admin, messages
from unfold.admin import ModelAdmin
from rest_framework.exceptions import ValidationError
from .models import AvailabilitySchedule, TeachingProfile
from .availability import ScheduleInput, expand_schedule, save_schedule


class WeeklyHoursWidget(forms.Widget):
    template_name='academy/widgets/weekly_hours.html'
    class Media:
        css={'all':['academy/weekly-hours.css']}
        js=['academy/weekly-hours.js']
    def format_value(self,value):
        if value in [None,'']:value=[{'day':day,'ranges':[]} for day in range(7)]
        return value if isinstance(value,str) else json.dumps(value)


class AvailabilityForm(forms.ModelForm):
    weekly=forms.JSONField(widget=WeeklyHoursWidget,label='Weekly hours')
    timezone=forms.ChoiceField(choices=[(name,name) for name in sorted(available_timezones())],label='Teaching time zone')
    class Meta:
        model=AvailabilitySchedule
        fields=['teacher','kind','timezone','start_date','end_date','duration_minutes','weekly']
        widgets={'start_date':forms.DateInput(attrs={'type':'date'}),'end_date':forms.DateInput(attrs={'type':'date'})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk and self.instance.kind=='trial':self.fields['duration_minutes'].widget.attrs['readonly']=True
        if not self.is_bound and not self.instance.pk:
            teacher_id=self.initial.get('teacher')
            profile=TeachingProfile.objects.filter(pk=teacher_id).first() if str(teacher_id).isdigit() else None
            from django.utils import timezone
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            zone=profile.timezone if profile else 'UTC'
            today=timezone.now().astimezone(ZoneInfo(zone)).date()
            self.initial.setdefault('timezone',zone)
            self.initial.setdefault('start_date',today)
            self.initial.setdefault('end_date',today+timedelta(days=27))
            self.initial.setdefault('duration_minutes',30)
    def clean(self):
        data=super().clean()
        keys=['kind','timezone','start_date','end_date','duration_minutes','weekly']
        payload={key:data.get(key,getattr(self.instance,key,None)) for key in keys}
        if any(value is None for value in payload.values()):return data
        serializer=ScheduleInput(data=payload)
        if not serializer.is_valid():raise forms.ValidationError(str(serializer.errors))
        try:expand_schedule(dict(serializer.validated_data))
        except ValidationError as error:raise forms.ValidationError(str(error.detail)) from error
        self.schedule_data=dict(serializer.validated_data)
        return data


@admin.register(AvailabilitySchedule)
class AvailabilityAdmin(ModelAdmin):
    form=AvailabilityForm
    list_display=['teacher','kind','timezone','start_date','end_date','duration_minutes','updated_at']
    list_select_related=['teacher__teacher','teacher__user']
    search_fields=['teacher__teacher__name','teacher__user__email']
    list_filter=['kind','timezone','teacher']
    autocomplete_fields=['teacher']
    fieldsets=(('Teacher & session',{'fields':('teacher','kind'),'description':'Select a registered teaching account. Manage its weekly hours here using the same protected slot generation as the teacher dashboard.'}),('Schedule settings',{'fields':('timezone','start_date','end_date','duration_minutes')}),('Availability',{'fields':('weekly',),'description':'Add multiple local-time ranges per day. Saving regenerates unreserved slots for this plan; bookings and individual slots are preserved.'}))
    def get_readonly_fields(self,request,obj=None):return ['teacher','kind'] if obj else []
    def save_model(self,request,obj,form,change):
        profile=form.cleaned_data.get('teacher') or obj.teacher
        result=save_schedule(profile,form.schedule_data)
        saved=AvailabilitySchedule.objects.get(teacher=profile,kind=form.schedule_data['kind'])
        for field in saved._meta.concrete_fields:setattr(obj,field.attname,getattr(saved,field.attname))
        obj._state.adding=False;obj._state.db=saved._state.db
        self.message_user(request,f"Availability saved: {result['created']} slots added, {result['removed']} unreserved slots removed, {result['preserved_reserved']} reserved slots preserved; {result['skipped_dst']} DST and {result['skipped_overlap']} overlapping slots skipped.",messages.SUCCESS)
    def has_delete_permission(self,request,obj=None):return False
