from django.contrib import admin
from .models import Teacher, Course
from .models import VolunteerApplication, NewsletterSubscriber
from .models import TeacherApplication, TeacherAttachment
from django.urls import path, reverse
from django.http import FileResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404
from django.utils.html import format_html
import io

class TeacherAttachmentInline(admin.TabularInline):
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
class TeacherApplicationAdmin(admin.ModelAdmin):
    list_display = ('first_name','last_name','email','country','created_at','reviewed')
    list_filter = ('reviewed','country','gender')
    search_fields = ('first_name','last_name','email','nickname')
    readonly_fields = ('request_id','created_at')
    inlines = [TeacherAttachmentInline]
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
class VolunteerApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'created_at', 'reviewed')
    list_filter = ('reviewed',)
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('request_id', 'created_at')

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'created_at', 'active')
    list_filter = ('active',)
    search_fields = ('email',)
    readonly_fields = ('created_at',)

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "currency", "published", "sort_order")
    list_filter = ("published", "currency")
    search_fields = ("name", "experience")
    prepopulated_fields = {"slug": ("name",)}
    list_editable = ("published", "sort_order")

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "price", "published", "sort_order")
    list_filter = ("published", "teacher")
    search_fields = ("title", "description")
    autocomplete_fields = ("teacher",)
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("published", "sort_order")

