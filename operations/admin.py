import re
from zoneinfo import available_timezones
from django import forms
from django.contrib import admin,messages
from django.utils import timezone
from unfold.admin import ModelAdmin
from catalog.stripe_gateway import encrypt
from .models import TelegramSettings,TelegramMessage
from .outbox import connection,valid_connection,clean
from .sender import api,TelegramFailure,deliver


class ConnectionForm(forms.ModelForm):
    timezone=forms.ChoiceField(choices=[(name,name) for name in sorted(available_timezones())],initial="Asia/Tehran")
    bot_token=forms.CharField(required=False,widget=forms.PasswordInput(render_value=False),help_text='Paste the BotFather token here. Stored encrypted; leave blank to retain the saved token. TELEGRAM_BOT_TOKEN in Vercel is also supported.')
    class Meta:model=TelegramSettings;exclude=['token_ciphertext']
    def clean(self):
        data=super().clean();token=data.get('bot_token','').strip()
        if token and not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',token):self.add_error('bot_token','Enter a valid BotFather token.')
        if data.get('enabled'):
            current=connection();chat=data.get('chat_id') or current.chat_id
            if not (token or current.token) or not chat:raise forms.ValidationError('Save the bot token and destination chat ID before enabling alerts.')
        return data
    def save(self,commit=True):
        obj=super().save(commit=False)
        if self.cleaned_data.get('bot_token'):obj.token_ciphertext=encrypt(self.cleaned_data['bot_token'].strip())
        if commit:obj.save()
        return obj


@admin.register(TelegramSettings)
class TelegramSettingsAdmin(ModelAdmin):
    form=ConnectionForm
    list_display=['__str__','enabled','chat_id','connection_status']
    readonly_fields=['connection_status']
    fields=['enabled','connection_status','bot_token','chat_id','thread_id','timezone','forms_enabled','crm_enabled','bookings_enabled','payments_enabled','accounts_enabled','admin_enabled','emails_enabled','errors_enabled','include_contact_details']
    actions=['find_chats','send_test']
    def has_module_permission(self,request):return request.user.is_superuser
    def has_view_permission(self,request,obj=None):return request.user.is_superuser
    def has_change_permission(self,request,obj=None):return request.user.is_superuser
    def has_add_permission(self,request):return request.user.is_superuser and not TelegramSettings.objects.exists()
    def has_delete_permission(self,request,obj=None):return False
    @admin.display(description='Connection configuration')
    def connection_status(self,obj):
        try:
            config=connection()
            return f"{'Enabled' if config.enabled else 'Disabled'} · token: {'configured' if config.token else 'missing'} · destination: {'configured' if config.chat_id else 'missing'} · delivery is verified only by a successful test or sent notification."
        except Exception:return 'Stored credentials cannot be read. Check payment encryption/secret-key configuration.'
    @admin.action(description='Find chat IDs from recent bot messages',permissions=['change'])
    def find_chats(self,request,queryset):
        try:
            config=connection()
            if not config.token:raise TelegramFailure('credentials_missing')
            updates=api('getUpdates',config,{'timeout':0,'limit':20,'allowed_updates':['message','channel_post']})
            chats={}
            for update in updates if isinstance(updates,list) else []:
                message=update.get('message') or update.get('channel_post') or {}
                chat=message.get('chat',{})
                if isinstance(chat.get('id'),int):chats[chat['id']]=clean(chat.get('title') or chat.get('first_name') or chat.get('type'),70)
            self.message_user(request,' · '.join(f'{name}: {chat_id}' for chat_id,name in chats.items()) if chats else 'No recent chat found. Send /start directly to the bot or /start@YourBotName in the target group, then try again.',messages.INFO)
        except TelegramFailure as error:self.message_user(request,'Chat discovery failed: '+error.code+'. Bots using a webhook cannot use getUpdates; enter the chat ID manually in that case.',messages.ERROR)
    @admin.action(description='Send a connection test to the configured chat',permissions=['change'])
    def send_test(self,request,queryset):
        try:
            config=connection()
            if not valid_connection(config):raise TelegramFailure('configuration_incomplete')
            payload={'chat_id':config.chat_id,'text':'RECITERA · Telegram connection test. Operational alerts are ready when enabled.','disable_web_page_preview':True}
            if config.thread_id:payload['message_thread_id']=config.thread_id
            api('sendMessage',config,payload)
            self.message_user(request,'Test message sent to the configured Telegram chat.' + (' Automatic alerts are disabled: enable Enabled and Forms enabled to receive teacher applications.' if not config.enabled or (config.row and not config.row.forms_enabled) else ''),messages.SUCCESS)
        except TelegramFailure as error:self.message_user(request,'Connection test failed: '+error.code,messages.ERROR)


@admin.register(TelegramMessage)
class TelegramMessageAdmin(ModelAdmin):
    list_display=['id','category','created_at','sent_at','dismissed_at','attempts','last_error']
    list_filter=['category',('sent_at',admin.EmptyFieldListFilter),('dismissed_at',admin.EmptyFieldListFilter)]
    search_fields=['key','text']
    readonly_fields=[field.name for field in TelegramMessage._meta.fields]
    actions=['retry','dismiss']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
    @admin.action(description='Retry unsent messages using the current destination',permissions=['change'])
    def retry(self,request,queryset):
        config=connection()
        if not valid_connection(config):self.message_user(request,'Configure a bot token and destination first.',messages.ERROR);return
        if not config.enabled:self.message_user(request,'Enable Telegram alerts before retrying notifications.',messages.ERROR);return
        pending=queryset.filter(sent_at__isnull=True,dismissed_at__isnull=True)
        count=pending.update(next_attempt_at=timezone.now(),chat_id=config.chat_id,thread_id=config.thread_id)
        # Keep active delivery leases so a concurrent worker cannot send twice.
        sent=0
        for pk in list(pending.values_list('pk',flat=True)[:3]):
            if deliver(pk):sent+=1
            else:break
        self.message_user(request,f'{sent} notifications sent now; {count-sent} remain queued. Check Last error for delivery failures.',messages.SUCCESS)
    @admin.action(description='Dismiss unsent notifications without deleting the audit record',permissions=['change'])
    def dismiss(self,request,queryset):
        count=queryset.filter(sent_at__isnull=True).update(dismissed_at=timezone.now())
        self.message_user(request,f'{count} unsent notifications dismissed.',messages.SUCCESS)
