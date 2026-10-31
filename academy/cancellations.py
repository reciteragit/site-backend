from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from .models import Booking, CancellationRequest
from .services import lock_teachers
from .booking_notices import queue_cancellation
from .views import AcademyView, AcademyWriteThrottle, booking_data


class Cancellation(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request,booking_id):
        class Input(serializers.Serializer):
            reason=serializers.CharField(max_length=2000,allow_blank=True,required=False,default='')
        data=Input(data=request.data);data.is_valid(raise_exception=True)
        with transaction.atomic():
            booking=get_object_or_404(Booking.objects.select_related('slot'),pk=booking_id,student=request.user)
            lock_teachers([booking.slot.teacher_id])
            booking=Booking.objects.select_for_update().select_related('slot__teacher__user','student','order').get(pk=booking.pk)
            existing=CancellationRequest.objects.filter(booking=booking).first()
            if existing:return Response(booking_data(booking,request.user))
            if booking.status!='confirmed' or booking.slot.starts_at<timezone.now()+timedelta(hours=24):
                raise PermissionDenied('Cancellation requests must be submitted at least 24 hours before a confirmed class.')
            CancellationRequest.objects.create(booking=booking,reason=data.validated_data['reason'])
            queue_cancellation(booking,'cancellation_request')
        return Response(booking_data(booking,request.user))


class CancellationDecision(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request,booking_id):
        class Input(serializers.Serializer):
            decision=serializers.ChoiceField(choices=['approve','decline'])
        data=Input(data=request.data);data.is_valid(raise_exception=True)
        desired='approved' if data.validated_data['decision']=='approve' else 'declined'
        with transaction.atomic():
            booking=get_object_or_404(Booking.objects.select_related('slot'),pk=booking_id,slot__teacher__user=request.user)
            lock_teachers([booking.slot.teacher_id])
            booking=Booking.objects.select_for_update().select_related('slot__teacher__user','student','order').get(pk=booking.pk)
            cancellation=get_object_or_404(CancellationRequest.objects.select_for_update(),booking=booking)
            if cancellation.status!='pending':
                if cancellation.status!=desired:raise PermissionDenied('This request has already been decided.')
                return Response(booking_data(booking,request.user))
            if booking.status!='confirmed' or booking.slot.starts_at<=timezone.now():raise PermissionDenied('Only an upcoming confirmed class can be cancelled.')
            cancellation.status=desired;cancellation.decided_at=timezone.now();cancellation.save(update_fields=['status','decided_at'])
            if desired=='approved':
                booking.status='cancelled';booking.save(update_fields=['status'])
            queue_cancellation(booking,'cancellation_'+desired)
        return Response(booking_data(booking,request.user))
