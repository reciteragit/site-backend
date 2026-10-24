from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Upper


def normalize_code(value):
    return (value or '').strip().upper()


class DiscountCode(models.Model):
    code = models.CharField(max_length=40,unique=True,validators=[RegexValidator(r'^[A-Za-z0-9_-]+$','Use letters, numbers, hyphens or underscores only.')],help_text='Case-insensitive code entered by the customer, for example WELCOME20.')
    name = models.CharField(max_length=160,help_text='Internal description for your team.')
    active = models.BooleanField(default=True)
    discount_type = models.CharField(max_length=10,choices=[('percentage','Percentage'),('fixed','Fixed amount (CAD)')],default='percentage')
    value = models.DecimalField(max_digits=9,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))],help_text='For percentage: 20 means 20%. For fixed amount: 20 means 20 CAD off the eligible products together.')
    minimum_amount = models.DecimalField(max_digits=9,decimal_places=2,default=0,validators=[MinValueValidator(0)],help_text='Minimum eligible amount in CAD, before discount. Zero means no minimum. The threshold is inclusive.')
    minimum_basis = models.CharField(max_length=20,choices=[('eligible_subtotal','Combined eligible product subtotal'),('individual_product','Each individual product price')],default='eligible_subtotal')
    all_products = models.BooleanField(default=True,help_text='Apply to all paid classes, recorded courses and payment-page products. Donations and free trials are excluded. Turn off to select specific products below.')
    teachers = models.ManyToManyField('catalog.Teacher',blank=True,related_name='discount_codes',help_text='Paid class bookings with these teachers.')
    courses = models.ManyToManyField('catalog.Course',blank=True,related_name='discount_codes')
    payment_items = models.ManyToManyField('catalog.PaymentItem',blank=True,related_name='discount_codes',verbose_name='Payment-page products')
    bundles = models.ManyToManyField("learning.CourseBundle",blank=True,related_name="discount_codes")
    allowed_user = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name='discount_codes',help_text='Optional: only this signed-in account can use the code. Leave empty for all customers.')
    starts_at = models.DateTimeField(null=True,blank=True)
    ends_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['code']
        constraints=[
            models.UniqueConstraint(Upper('code'),name='catalog_discount_code_upper_unique'),
            models.CheckConstraint(condition=models.Q(value__gt=0)&(models.Q(discount_type='fixed')|models.Q(discount_type='percentage',value__lte=100)),name='catalog_discount_valid_value'),
            models.CheckConstraint(condition=models.Q(minimum_amount__gte=0),name='catalog_discount_minimum_nonnegative'),
        ]
    def clean(self):
        super().clean()
        self.code=normalize_code(self.code)
        if self.discount_type=='percentage' and self.value is not None and self.value>100:
            raise ValidationError({'value':'Percentage must be between 0.01 and 100.'})
        if self.starts_at and self.ends_at and self.ends_at<=self.starts_at:
            raise ValidationError({'ends_at':'End must be later than the start.'})
    def save(self,*args,**kwargs):
        self.code=normalize_code(self.code)
        return super().save(*args,**kwargs)
    def __str__(self):return self.code
