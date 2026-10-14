from django.db import models
from django.core.validators import MinValueValidator
from .validators import validate_languages

class Teacher(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
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
