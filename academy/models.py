import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='academy_profile')
    timezone = models.CharField(max_length=100, default='UTC')


class AccessToken(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()


class TeachingProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='teaching_profile')
    teacher = models.OneToOneField('catalog.Teacher', on_delete=models.PROTECT, related_name='booking_profile')
    biography = models.TextField(blank=True)
    timezone = models.CharField(max_length=100, default='UTC')
    meeting_url = models.URLField(max_length=1000, blank=True, default='https://lms.recitera.com/', help_text='HTTPS class destination. Shared only for confirmed bookings.')
    meeting_provider = models.CharField(max_length=10, default='lms', choices=[('meet','Google Meet'),('zoom','Zoom'),('lms','Recitera LMS')])
    approved = models.BooleanField(default=False, help_text='Only staff can approve a teacher to accept paid bookings.')
    def __str__(self): return self.teacher.name


class AvailabilitySchedule(models.Model):
    teacher = models.ForeignKey(TeachingProfile, on_delete=models.CASCADE, related_name='availability_schedules')
    kind = models.CharField(max_length=5, default='class', choices=[('class', 'Paid class'), ('trial', 'Free trial')])
    timezone = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    weekly = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['teacher', 'kind'], name='academy_schedule_per_session_kind')]


class Slot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(TeachingProfile, on_delete=models.PROTECT, related_name='slots')
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    active = models.BooleanField(default=True)
    kind = models.CharField(max_length=5, default='class', choices=[('class', 'Paid class'), ('trial', 'Free trial')])
    schedule = models.ForeignKey(AvailabilitySchedule, null=True, blank=True, on_delete=models.SET_NULL, related_name='slots')
    class Meta:
        ordering = ['starts_at']
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=models.F('starts_at')), name='academy_positive_slot_duration')]
        indexes = [models.Index(fields=['teacher', 'starts_at', 'ends_at'])]


class CartItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    slot = models.ForeignKey(Slot, on_delete=models.CASCADE)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'slot'], name='academy_unique_cart_slot')]


class Order(models.Model):
    subtotal = models.DecimalField(max_digits=10,decimal_places=2,default=0,db_default=0)
    discount_amount = models.DecimalField(max_digits=10,decimal_places=2,default=0,db_default=0)
    discount_code = models.CharField(max_length=40,blank=True,default="",db_default="")
    discount = models.ForeignKey('catalog.DiscountCode',null=True,blank=True,on_delete=models.SET_NULL,related_name='class_orders')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    email = models.EmailField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='CAD')
    mode = models.CharField(max_length=4)
    status = models.CharField(max_length=20, default='held', choices=[(v,v) for v in ['held','pending','paid','expired','failed','payment_review']])
    expires_at = models.DateTimeField()
    stripe_session_id = models.CharField(max_length=200, blank=True)
    checkout_url = models.URLField(max_length=2000, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']


class Booking(models.Model):
    original_amount = models.DecimalField(max_digits=8,decimal_places=2,default=0,db_default=0)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='bookings')
    slot = models.ForeignKey(Slot, on_delete=models.PROTECT, related_name='bookings')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    student_timezone = models.CharField(max_length=100)
    teacher_timezone = models.CharField(max_length=100)
    teacher_name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    meeting_url = models.URLField(max_length=1000)
    status = models.CharField(max_length=20, default='held', choices=[(v,v) for v in ['held','confirmed','expired','failed','payment_review']])
    class Meta:
        ordering = ['slot__starts_at']
        constraints = [models.UniqueConstraint(fields=['slot'], condition=Q(status__in=['held','confirmed']), name='academy_one_active_booking_per_slot')]


class EmailDelivery(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name='emails')
    recipient = models.EmailField()
    recipient_timezone = models.CharField(max_length=100)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    leased_until = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=100, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['booking','recipient'], name='academy_one_booking_email_per_recipient')]


class GoogleIdentity(models.Model):
    subject = models.CharField(max_length=255, unique=True, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_identity')
    email = models.EmailField(max_length=254, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)


class GoogleAuthorization(models.Model):
    digest = models.CharField(max_length=64, primary_key=True, editable=False)
    binding_digest = models.CharField(max_length=64, editable=False)
    nonce_digest = models.CharField(max_length=64, editable=False)
    verifier_ciphertext = models.TextField(editable=False)
    redirect_uri = models.URLField(max_length=500)
    next_path = models.CharField(max_length=300, default='/account')
    timezone = models.CharField(max_length=100, default='UTC')
    mode = models.CharField(max_length=5, choices=[('login','Login'),('link','Link')])
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
