from django import forms
from django.contrib import admin,messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from .payment_models import StripeSettings,Donor,PaymentOrder,PaymentItem,StripeEvent
from .stripe_gateway import encrypt,credentials,ready,client,valid_origin

class StripeSettingsForm(forms.ModelForm):
    test_secret_key=forms.CharField(required=False,widget=forms.PasswordInput(render_value=False),help_text='Write-only. Leave blank to keep the saved key. Use sk_test_…')
    test_webhook_secret=forms.CharField(required=False,widget=forms.PasswordInput(render_value=False),help_text='Write-only. Use whsec_…')
    live_secret_key=forms.CharField(required=False,widget=forms.PasswordInput(render_value=False),help_text='Write-only. Leave blank to keep the saved key. Use sk_live_…')
    live_webhook_secret=forms.CharField(required=False,widget=forms.PasswordInput(render_value=False),help_text='Write-only. Use whsec_…')
    class Meta:
        model=StripeSettings
        fields=['enabled','mode','frontend_origin','donations_enabled','courses_enabled','lessons_enabled','other_payments_enabled']
    def clean(self):
        values=super().clean()
        if values.get('frontend_origin') and not valid_origin(values['frontend_origin']):raise ValidationError('Use a public HTTPS origin without a path, query or fragment.')
        for mode in ['test','live']:
            key=values.get(f'{mode}_secret_key','');secret=values.get(f'{mode}_webhook_secret','')
            if key and not key.startswith(f'sk_{mode}_'):self.add_error(f'{mode}_secret_key','The Stripe key does not match this mode.')
            if secret and not secret.startswith('whsec_'):self.add_error(f'{mode}_webhook_secret','Enter a Stripe webhook signing secret.')
        if values.get('enabled'):
            mode=values.get('mode','test');old_key,old_secret=credentials(self.instance,mode)
            if not (values.get(f'{mode}_secret_key') or old_key) or not (values.get(f'{mode}_webhook_secret') or old_secret):raise ValidationError('Configure the secret key and webhook signing secret before enabling Stripe.')
        return values
    def save(self,commit=True):
        obj=super().save(commit=False)
        for mode in ['test','live']:
            for field,target in [('secret_key','secret_ciphertext'),('webhook_secret','webhook_ciphertext')]:
                value=self.cleaned_data.get(f'{mode}_{field}')
                if value:setattr(obj,f'{mode}_{target}',encrypt(value))
        if commit:obj.save()
        return obj

@admin.register(StripeSettings)
class StripeSettingsAdmin(admin.ModelAdmin):
    form=StripeSettingsForm
    list_display=['__str__','enabled','mode','connection_status']
    fields=['enabled','mode','frontend_origin','connection_status','webhook_endpoint','donations_enabled','courses_enabled','lessons_enabled','other_payments_enabled','test_secret_key','test_webhook_secret','live_secret_key','live_webhook_secret']
    readonly_fields=['connection_status','webhook_endpoint']
    actions=['verify_connection']
    def has_module_permission(self,request):return request.user.is_superuser
    def has_view_permission(self,request,obj=None):return request.user.is_superuser
    def has_change_permission(self,request,obj=None):return request.user.is_superuser
    def has_add_permission(self,request):return request.user.is_superuser and not StripeSettings.objects.exists()
    def has_delete_permission(self,request,obj=None):return False
    def connection_status(self,obj):
        if not obj:return 'Not configured'
        key,secret=credentials(obj)
        return f'{obj.mode.upper()} · key: {"configured" if key else "missing"} · webhook: {"configured" if secret else "missing"} · {"enabled" if ready(obj) else "inactive"}'
    def webhook_endpoint(self,obj):
        return 'https://site-backend-one.vercel.app/api/payments/stripe/webhook/ — Register checkout.session.completed, checkout.session.async_payment_succeeded, checkout.session.async_payment_failed and checkout.session.expired in Stripe. Store the signing secret above.'
    @admin.action(description='Verify Stripe API connection (no charge)')
    def verify_connection(self,request,queryset):
        for config in queryset:
            try:
                account=client(config).v1.accounts.retrieve_current()
                self.message_user(request,f'Stripe API connected: {account.id}. Webhook delivery must be tested separately.',messages.SUCCESS)
            except Exception:self.message_user(request,'Stripe connection could not be verified. Check the key and account access.',messages.ERROR)

@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display=['email','first_name','last_name','country','created_at'];search_fields=['email','first_name','last_name'];readonly_fields=['created_at']

@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display=['id','purpose','donor','amount','currency','status','mode','anonymous','created_at'];list_filter=['purpose','status','mode','anonymous'];search_fields=['donor__email','first_name','last_name','stripe_session_id'];readonly_fields=[f.name for f in PaymentOrder._meta.fields]
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(PaymentItem)
class PaymentItemAdmin(admin.ModelAdmin):
    list_display=['title','slug','amount','active','payment_page'];prepopulated_fields={'slug':['title']}
    def payment_page(self,obj):
        config=StripeSettings.objects.first()
        if not config:return 'Configure Stripe settings first'
        return format_html('<a href="{}/pay/other/{}" target="_blank" rel="noopener">Open payment page</a>',config.frontend_origin.rstrip('/'),obj.slug)

@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display=['event_id','event_type','processed_at'];readonly_fields=['event_id','event_type','processed_at']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
