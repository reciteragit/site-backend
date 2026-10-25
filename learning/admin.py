from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from unfold.admin import ModelAdmin,TabularInline
from .models import Episode,CourseBundle,Enrollment,EpisodeProgress,CoursePurchase


class EpisodeInline(TabularInline):
    model=Episode
    extra=0
    show_change_link=True
    fields=['title','video_provider','video_url','is_free','duration_seconds','published','sort_order']


@admin.register(Episode)
class EpisodeAdmin(ModelAdmin):
    actions=['publish_episodes']
    list_display=['title','course','is_free','duration_seconds','published','sort_order']
    list_filter=['is_free','published','course']
    search_fields=['title','course__title']
    autocomplete_fields=['course']
    list_select_related=['course']
    fieldsets=(('Episode',{'fields':('course','title','description','sort_order')}),('Video & access',{'fields':('video_provider','video_url','duration_seconds','is_free','published')}))

    @admin.action(description='Publish selected episodes with valid video links', permissions=['change'])
    def publish_episodes(self,request,queryset):
        published=skipped=0
        for episode in queryset:
            episode.published=True
            try:episode.full_clean()
            except ValidationError:
                skipped+=1
                continue
            episode.save(update_fields=['published'])
            published+=1
        self.message_user(request,f'{published} episodes published; {skipped} skipped because their video or episode settings are incomplete.',messages.WARNING if skipped else messages.SUCCESS)

    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        if not obj.published:
            self.message_user(request,'This episode is saved as a draft. Enable Published to show it on the website and open course enrolment.',messages.WARNING)


class BundleForm(forms.ModelForm):
    class Meta:model=CourseBundle;fields='__all__'
    def clean(self):
        data=super().clean();courses=data.get('courses')
        if data.get('published') and (not courses or any(c.delivery_mode!='platform' or not c.published or c.currency!='CAD' or not c.episodes.filter(published=True).exists() for c in courses)):
            raise forms.ValidationError('Publish a package only after selecting published Recitera-platform courses priced in CAD and containing published episodes.')
        return data


@admin.register(CourseBundle)
class BundleAdmin(ModelAdmin):
    form=BundleForm
    list_display=['title','package_price','discount_percent','published','sort_order']
    search_fields=['title','slug']
    list_filter=['published']
    prepopulated_fields={'slug':['title']}
    autocomplete_fields=['courses']
    readonly_fields=['package_price']
    fieldsets=(('Package',{'fields':('title','slug','description','image','courses')}),('Price & publication',{'fields':('discount_percent','package_price','published','sort_order'),'description':'Price is the sum of included courses less the package percentage. Purchased access keeps its original course list even if the package changes later.'}))
    @admin.display(description='Package price (CAD)')
    def package_price(self,obj):return f'{obj.price:.2f} (original {obj.base_price:.2f})' if obj and obj.pk else 'Save the selected courses to calculate the price.'


@admin.register(Enrollment)
class EnrollmentAdmin(ModelAdmin):
    list_display=['user','course','active','enrolled_at','source_order']
    search_fields=['user__email','course__title']
    list_filter=['active','course']
    autocomplete_fields=['user','course']
    readonly_fields=['source_order','enrolled_at']
    list_select_related=['user','course','source_order']


@admin.register(EpisodeProgress)
class ProgressAdmin(ModelAdmin):
    list_display=['user','episode','position_seconds','watched_seconds','completed','updated_at']
    search_fields=['user__email','episode__title','episode__course__title']
    list_filter=['completed','episode__course']
    readonly_fields=[f.name for f in EpisodeProgress._meta.fields]
    list_select_related=['user','episode']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(CoursePurchase)
class CoursePurchaseAdmin(ModelAdmin):
    list_display=['order','course']
    readonly_fields=['order','course']
    search_fields=['order__buyer__email','course__title']
    list_select_related=['order','course']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
