import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator

class StripeSettings(models.Model):
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=4,choices=[('test','Test / sandbox'),('live','Live')],default='test')
    frontend_origin = models.URLField(default='https://site-pearl-one-38.vercel.app',help_text='Public frontend origin, without a path. Checkout returns here.')
    donations_enabled = models.BooleanField(default=True)
    courses_enabled = models.BooleanField(default=False)
    lessons_enabled = models.BooleanField(default=False)
    other_payments_enabled = models.BooleanField(default=False)
    test_secret_ciphertext = models.TextField(blank=True,editable=False)
    live_secret_ciphertext = models.TextField(blank=True,editable=False)
    test_webhook_ciphertext = models.TextField(blank=True,editable=False)
    live_webhook_ciphertext = models.TextField(blank=True,editable=False)
    def __str__(self):return 'Stripe connection settings'

class Donor(models.Model):
    email = models.EmailField(max_length=254,unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100,blank=True)
    phone = models.CharField(max_length=40,blank=True)
    country = models.CharField(max_length=100,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):return self.email

class PaymentItem(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=9,decimal_places=2,validators=[MinValueValidator(Decimal('1.00'))])
    active = models.BooleanField(default=True)
    def __str__(self):return self.title

class PaymentOrder(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    request_id = models.UUIDField(unique=True,editable=False)
    donor = models.ForeignKey(Donor,on_delete=models.PROTECT,related_name='payments')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100,blank=True)
    purpose = models.CharField(max_length=20,choices=[('donation','Donation'),('course','Course'),('lesson','Lesson'),('other','Other payment')])
    phone = models.CharField(max_length=40,blank=True)
    country = models.CharField(max_length=100,blank=True)
    reference = models.CharField(max_length=200,default='general')
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=9,decimal_places=2)
    currency = models.CharField(max_length=3,default='CAD')
    comment = models.TextField(blank=True)
    anonymous = models.BooleanField(default=False)
    mode = models.CharField(max_length=4,default='test')
    status = models.CharField(max_length=20,choices=[(v,v.title()) for v in ['registered','pending','paid','failed','expired']],default='registered')
    stripe_session_id = models.CharField(max_length=200,blank=True)
    stripe_payment_intent = models.CharField(max_length=200,blank=True)
    checkout_url = models.URLField(max_length=2000,blank=True)
    checkout_expires_at = models.DateTimeField(null=True,blank=True)
    paid_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:ordering=['-created_at']
    def __str__(self):return f'{self.purpose}: {self.amount} {self.currency} ({self.status})'

class StripeEvent(models.Model):
    event_id = models.CharField(max_length=200,unique=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)
