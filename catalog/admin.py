from django import forms
from unfold.admin import ModelAdmin, TabularInline
from django.contrib import admin
from . import payment_admin, discount_admin
from .models import Teacher, Course
from .models import VolunteerApplication, NewsletterSubscriber, ScholarshipApplication
from .models import TeacherApplication, TeacherAttachment
from django.urls import path, reverse
from django.http import FileResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404
from django.utils.html import format_html
import io

class TeacherAttachmentInline(TabularInline):
    model = TeacherAttachment
    extra = 0
    fields = ('category','filename','size','download')
    readonly_fields = fields
    can_delete = False
    def has_add_permission(self,request,obj=None):
        return False
    def download(self,obj):
        if not obj.pk:return ''
        return format_html('<a href="{}">Download attachment</a>',reverse('admin:teacher_attachment_download',args=[obj.application_id,obj.pk]))

@admin.register(TeacherApplication)
class TeacherApplicationAdmin(ModelAdmin):
    list_per_page = 25
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Application', {'fields':('full_name','email','whatsapp','preferences','reviewed')}),
        ('Additional details', {'classes':('collapse',),'fields':(('first_name','last_name'),'nickname','gender','date_of_birth','years_of_experience','country','timezone','specializations','languages','other_languages','referral','sample_url')}),
        ('Record', {'fields':('request_id','created_at')}),
    )
    list_display = ('applicant_name','email','whatsapp','created_at','reviewed')
    list_filter = ('reviewed','country','gender')
    search_fields = ('full_name','first_name','last_name','email','nickname')
    readonly_fields = ('request_id','created_at')
    inlines = [TeacherAttachmentInline]
    @admin.display(description='Full name')
    def applicant_name(self,obj):return str(obj)
    def get_form(self,request,obj=None,**kwargs):
        form=super().get_form(request,obj,**kwargs)
        for name in ['specializations','languages']:
            if name in form.base_fields:form.base_fields[name].required=False
        return form
    def get_urls(self):
        return [path('<int:application_id>/attachment/<int:attachment_id>/',self.admin_site.admin_view(self.download_attachment),name='teacher_attachment_download')]+super().get_urls()
    def download_attachment(self,request,application_id,attachment_id):
        application=get_object_or_404(TeacherApplication,pk=application_id)
        if not self.has_view_permission(request,application):return HttpResponseForbidden()
        item=get_object_or_404(TeacherAttachment,pk=attachment_id,application=application)
        response=FileResponse(io.BytesIO(bytes(item.data)),as_attachment=True,filename=item.filename,content_type='application/octet-stream')
        response['Cache-Control']='private, no-store'
        response['X-Content-Type-Options']='nosniff'
        return response

@admin.register(VolunteerApplication)
class VolunteerApplicationAdmin(ModelAdmin):
    list_display = ('name', 'email', 'created_at', 'reviewed')
    list_filter = ('reviewed',)
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('request_id', 'created_at')

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(ModelAdmin):
    list_display = ('email', 'created_at', 'active')
    list_filter = ('active',)
    search_fields = ('email',)
    readonly_fields = ('created_at',)

@admin.register(Teacher)
class TeacherAdmin(ModelAdmin):
    list_per_page = 25
    search_help_text = "Find a teacher by name or teaching experience."
    fieldsets = (
        ('Public profile', {'fields':('name','slug','image','profile_url','biography')}),
        ('Teaching details', {'fields':('based_in','experience','languages','specialities')}),
        ('Class pricing', {'fields':(('price','currency'),)}),
        ('Publishing', {'fields':(('published','sort_order'),)}),
    )
    list_display = ("name", "price", "currency", "published", "sort_order")
    list_filter = ("published", "currency")
    search_fields = ("name", "experience")
    prepopulated_fields = {"slug": ("name",)}
    list_editable = ("published", "sort_order")

class CourseForm(forms.ModelForm):
    class Meta:model=Course;fields='__all__'
    def clean(self):
        data=super().clean()
        if data.get('delivery_mode')=='platform' and data.get('currency')!='CAD':self.add_error('currency','Recitera course checkout currently uses CAD.')
        if self.instance.pk and self.instance.delivery_mode=='platform' and data.get('delivery_mode')=='external':
            from learning.models import Enrollment,CoursePurchase
            if Enrollment.objects.filter(course=self.instance).exists() or CoursePurchase.objects.filter(course=self.instance).exists():self.add_error('delivery_mode','This course has enrolments or purchases. Unpublish it instead of changing its delivery mode.')
        if data.get('delivery_mode')=='external' and not data.get('course_url'):self.add_error('course_url','Enter the external academy course URL.')
        return data


@admin.register(Course)
class CourseAdmin(ModelAdmin):
    form=CourseForm
    from learning.admin import EpisodeInline
    inlines=[EpisodeInline]
    def get_changeform_initial_data(self,request):
        return {**super().get_changeform_initial_data(request),"delivery_mode":"platform","published":False}
    list_per_page = 25
    fieldsets = (
        ('Course details', {'fields':('title','slug','teacher','delivery_mode','image','description','course_url')}),
        ('Pricing & publishing', {'fields':(('price','currency'),('published','sort_order'))}),
    )
    list_display = ("title", "teacher", "price", "published", "sort_order")
    list_filter = ("published", "teacher")
    search_fields = ("title", "description")
    autocomplete_fields = ("teacher",)
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("published", "sort_order")


@admin.register(ScholarshipApplication)
class ScholarshipApplicationAdmin(ModelAdmin):
    list_display = ('name', 'email', 'whatsapp', 'created_at', 'reviewed')
    list_filter = ('reviewed', 'created_at')
    search_fields = ('name', 'email', 'whatsapp', 'message')
    readonly_fields = ('request_id', 'created_at')
