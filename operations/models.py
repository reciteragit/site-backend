from django.db import models
from django.core.validators import RegexValidator

CHAT=RegexValidator(r'^(?:-?\d+|@[A-Za-z][A-Za-z0-9_]{4,})$','Enter a numeric Telegram chat ID or @channel username.')


class TelegramSettings(models.Model):
    enabled=models.BooleanField(default=False)
    token_ciphertext=models.TextField(blank=True,editable=False)
    chat_id=models.CharField(max_length=100,blank=True,validators=[CHAT])
    thread_id=models.PositiveIntegerField(null=True,blank=True,help_text='Optional topic/message thread ID for forum groups.')
    timezone=models.CharField(max_length=100,default='Asia/Tehran')
    forms_enabled=models.BooleanField(default=True)
    crm_enabled=models.BooleanField(default=True)
    bookings_enabled=models.BooleanField(default=True)
    payments_enabled=models.BooleanField(default=True)
    accounts_enabled=models.BooleanField(default=True)
    admin_enabled=models.BooleanField(default=True)
    emails_enabled=models.BooleanField(default=True)
    errors_enabled=models.BooleanField(default=True)
    include_contact_details=models.BooleanField(default=False,help_text='Opt in to sending applicant names, email addresses and phone numbers to the selected chat. Private notes, passwords and classroom links are never included.')
    def save(self,*args,**kwargs):self.pk=1;super().save(*args,**kwargs)
    def __str__(self):return 'Telegram operations connection'


class TelegramMessage(models.Model):
    key=models.CharField(max_length=200,unique=True)
    category=models.CharField(max_length=20)
    text=models.TextField()
    chat_id=models.CharField(max_length=100)
    thread_id=models.PositiveIntegerField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    dismissed_at=models.DateTimeField(null=True,blank=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    next_attempt_at=models.DateTimeField(null=True,blank=True)
    attempts=models.PositiveIntegerField(default=0)
    leased_until=models.DateTimeField(null=True,blank=True)
    last_error=models.CharField(max_length=100,blank=True)
    telegram_message_id=models.BigIntegerField(null=True,blank=True)
    class Meta:ordering=['-created_at']
    def __str__(self):return self.category+' · '+str(self.pk)
