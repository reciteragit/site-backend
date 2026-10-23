from django.db import models
from django.core.validators import MinValueValidator
from .validators import validate_languages
import uuid
from .payment_models import StripeSettings, Donor, PaymentItem, PaymentOrder, StripeEvent

class TeacherApplication(models.Model):
    request_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=200, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    nickname = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=10, blank=True, choices=[(v,v) for v in ['Male','Female','Other']])
    date_of_birth = models.DateField(null=True, blank=True)
    whatsapp = models.CharField(max_length=40)
    years_of_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    email = models.EmailField(max_length=254)
    country = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(max_length=100, blank=True)
    specializations = models.JSONField(default=list)
    languages = models.JSONField(default=list)
    other_languages = models.CharField(max_length=200, blank=True)
    referral = models.CharField(max_length=300, blank=True)
    preferences = models.TextField(blank=True)
    sample_url = models.URLField(max_length=1000, blank=True)
    reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return self.full_name or f'{self.first_name} {self.last_name}'.strip()

class TeacherAttachment(models.Model):
    application = models.ForeignKey(TeacherApplication, on_delete=models.CASCADE, related_name='attachments')
    category = models.CharField(max_length=30)
    filename = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    data = models.BinaryField(editable=False)
    def __str__(self):
        return self.filename

class VolunteerApplication(models.Model):
    request_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(max_length=254)
    whatsapp = models.CharField(max_length=40)
    areas = models.JSONField(default=list)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed = models.BooleanField(default=False)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return self.name

class NewsletterSubscriber(models.Model):
    email = models.EmailField(max_length=254, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return self.email

class Teacher(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    biography = models.TextField(blank=True)
    based_in = models.CharField(max_length=100, blank=True)
    specialities = models.JSONField(default=list, blank=True)
    experience = models.CharField(max_length=80)
    languages = models.JSONField(default=list, validators=[validate_languages])
    image = models.CharField(max_length=500, help_text="Frontend /assets/ path or public HTTPS image URL")
    profile_url = models.URLField()
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="CAD")
    sort_order = models.PositiveIntegerField(default=0)
    published = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.name

class Course(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, related_name="courses")
    course_url = models.URLField()
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="CAD")
    sort_order = models.PositiveIntegerField(default=0)
    published = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class ScholarshipApplication(models.Model):
    request_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    whatsapp = models.CharField(max_length=40)
    email = models.EmailField(max_length=254)
    message = models.TextField(blank=True)
    reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return self.name

from .discount_models import DiscountCode
