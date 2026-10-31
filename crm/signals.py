from django.db.models.signals import post_save
from django.dispatch import receiver
from academy.models import Booking
from catalog.models import ScholarshipApplication
from catalog.payment_models import PaymentOrder
from .models import TrialRequest
from .services import sync_booking,sync_request,sync_scholarship,sync_conversion

@receiver(post_save,sender=ScholarshipApplication)
def scholarship_saved(sender,instance,raw=False,**kwargs):
    if not raw:sync_scholarship(instance)

@receiver(post_save,sender=TrialRequest)
def request_saved(sender,instance,raw=False,**kwargs):
    if not raw:sync_request(instance)

@receiver(post_save,sender=Booking)
def booking_saved(sender,instance,raw=False,**kwargs):
    if not raw:
        sync_booking(instance)
        if instance.status=='confirmed':sync_conversion(instance.student_id)

@receiver(post_save,sender=PaymentOrder)
def payment_saved(sender,instance,raw=False,**kwargs):
    if not raw and instance.status=='paid':sync_conversion(instance.buyer_id)

from academy.models import Order
@receiver(post_save,sender=Order)
def class_order_saved(sender,instance,raw=False,**kwargs):
    if not raw and instance.status=='paid':sync_conversion(instance.user_id)
