from django.contrib import admin
from .models import Teacher, Course
from .models import VolunteerApplication, NewsletterSubscriber

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

