from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import Enrollment,CoursePurchase,CourseBundle
from catalog.models import Course


def has_access(user,course):
    return bool(user and user.is_authenticated and Enrollment.objects.filter(user=user,course=course,active=True).exists())


def can_watch(user,episode):
    owned=has_access(user,episode.course)
    visible=episode.course.delivery_mode=='platform' and (owned or (episode.course.published and episode.course.teacher.published))
    return visible and episode.published and (owned or episode.is_free or episode.course.price==0)


def purchase_courses(purpose,reference):
    if purpose=='course':
        course=Course.objects.filter(slug=reference,delivery_mode='platform',published=True,teacher__published=True,currency='CAD').first()
        courses=[course] if course else []
    elif purpose=='bundle':
        bundle=CourseBundle.objects.filter(slug=reference,published=True).prefetch_related('courses__teacher').first()
        courses=list(bundle.courses.all()) if bundle else []
    else:return []
    if not courses or any(c.delivery_mode!='platform' or not c.published or not c.teacher.published or c.currency!='CAD' or not c.episodes.filter(published=True).exists() for c in courses):
        raise ValidationError('This course content is not ready for enrolment yet.')
    return courses


def grant_order_access(order):
    if order.status!='paid' or not order.buyer_id:return
    for line in order.course_lines.all():
        enrollment,created=Enrollment.objects.get_or_create(user_id=order.buyer_id,course=line.course,defaults={'source_order':order,'active':True})
        if not created and not enrollment.active:
            # Explicit administrator revocation is not silently undone by a retry.
            continue


def snapshot_purchase(order,courses):
    for course in courses:CoursePurchase.objects.get_or_create(order=order,course=course)
