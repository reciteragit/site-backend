from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from catalog.forms import FormThrottle
from academy.views import AcademyView,AcademyWriteThrottle
from academy.timezones import zone
from academy.models import Booking
from .models import TrialRequest,TrialRecord,Lead
from .services import record_outcome,event


class TrialRegistration(APIView):
    permission_classes=[AllowAny];authentication_classes=[];throttle_classes=[FormThrottle]
    def post(self,request):
        class Input(serializers.Serializer):
            request_id=serializers.UUIDField()
            name=serializers.CharField(max_length=150)
            email=serializers.EmailField(max_length=254)
            whatsapp=serializers.RegexField(r'^[+0-9() .#*=\-]{6,40}$',required=False,allow_blank=True)
            timezone=serializers.CharField(max_length=100,default='UTC')
            language=serializers.CharField(max_length=80,allow_blank=True,required=False,default='')
            goals=serializers.CharField(max_length=2000,allow_blank=True,required=False,default='')
            campaign=serializers.CharField(max_length=150,allow_blank=True,required=False,default='')
            website=serializers.CharField(required=False,allow_blank=True)
        data=Input(data=request.data);data.is_valid(raise_exception=True)
        values=dict(data.validated_data);zone(values['timezone'])
        if values.pop('website',''):return Response({'success':True},status=201)
        key=values.pop('request_id')
        with transaction.atomic():TrialRequest.objects.get_or_create(request_id=key,defaults=values)
        return Response({'success':True},status=201)


class TeacherTrialReport(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request,booking_id):
        class Input(serializers.Serializer):
            outcome=serializers.ChoiceField(choices=['attended','no_show'])
            assessed_level=serializers.CharField(max_length=200,allow_blank=True,default='')
            notes=serializers.CharField(max_length=5000,allow_blank=True,default='')
        data=Input(data=request.data);data.is_valid(raise_exception=True)
        with transaction.atomic():
            trial=get_object_or_404(TrialRecord.objects.select_for_update().select_related('booking__slot','lead'),booking_id=booking_id,booking__slot__teacher__user=request.user,booking__status='confirmed')
            if trial.booking.slot.ends_at>timezone.now():raise PermissionDenied('Record attendance after the trial ends.')
            record_outcome(trial,data.validated_data['outcome'],data.validated_data['assessed_level'],data.validated_data['notes'],request.user)
        return Response({'saved':True})


class StudentTrialFeedback(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request,booking_id):
        class Input(serializers.Serializer):
            rating=serializers.IntegerField(min_value=1,max_value=5)
            feedback=serializers.CharField(max_length=3000,allow_blank=True,default='')
            interest=serializers.ChoiceField(choices=['continue','help','not_continue'])
        data=Input(data=request.data);data.is_valid(raise_exception=True)
        with transaction.atomic():
            trial=get_object_or_404(TrialRecord.objects.select_for_update().select_related('booking__slot','lead'),booking_id=booking_id,booking__student=request.user,booking__status='confirmed')
            if trial.booking.slot.ends_at>timezone.now():raise PermissionDenied('Share feedback after your trial ends.')
            trial.feedback_rating=data.validated_data['rating'];trial.feedback=data.validated_data['feedback'];trial.interest=data.validated_data['interest'];trial.feedback_at=timezone.now();trial.save(update_fields=['feedback_rating','feedback','interest','feedback_at'])
            lead=Lead.objects.select_for_update().get(pk=trial.lead_id)
            if trial.interest=='not_continue':
                lead.do_not_contact=True
                if lead.stage!='converted':lead.stage='dropped';lead.drop_reason=trial.feedback or 'Not continuing after trial'
                lead.save(update_fields=['do_not_contact','stage','drop_reason','updated_at'])
            event(lead,'feedback:'+str(trial.pk),'trial_feedback',trial.interest,request.user)
        return Response({'saved':True})


class ClaimTrialRequest(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request):
        from django.core import signing
        from .models import Communication,LeadEvent,LeadNote
        from .services import sync_conversion
        class Input(serializers.Serializer):
            token=serializers.CharField(max_length=2000)
        data=Input(data=request.data);data.is_valid(raise_exception=True)
        try:payload=signing.loads(data.validated_data['token'],salt='recitera-crm-trial-claim',max_age=7*24*3600)
        except signing.BadSignature:raise serializers.ValidationError('This link is invalid or expired. Contact Recitera to connect your request.')
        with transaction.atomic():
            enquiry=get_object_or_404(TrialRequest,request_id=payload.get('request_id'))
            if enquiry.email.lower()!=request.user.email.lower():raise PermissionDenied('Sign in using the same email address as your trial request.')
            source=get_object_or_404(Lead.objects.select_for_update(),trial_request=enquiry)
            canonical,_=Lead.objects.get_or_create(key='user:'+str(request.user.pk),defaults={'source':'trial_request','user':request.user,'name':request.user.get_full_name() or source.name,'email':request.user.email,'timezone':source.timezone})
            canonical=Lead.objects.select_for_update().get(pk=canonical.pk)
            if source.pk!=canonical.pk:
                if source.merged_into_id and source.merged_into_id!=canonical.pk:raise PermissionDenied('This enquiry is already connected to another account.')
                if not source.merged_into_id:
                    for field in ['whatsapp','language','goals','campaign']:
                        if not getattr(canonical,field):setattr(canonical,field,getattr(source,field))
                    canonical.do_not_contact=canonical.do_not_contact or source.do_not_contact
                    if source.stage=='dropped' and canonical.stage!='converted':canonical.stage='dropped';canonical.drop_reason=source.drop_reason
                    if not canonical.owner_id:canonical.owner=source.owner
                    canonical.save()
                    LeadEvent.objects.filter(lead=source).update(lead=canonical)
                    LeadNote.objects.filter(lead=source).update(lead=canonical)
                    Communication.objects.filter(lead=source).update(lead=canonical)
                    source.merged_into=canonical;source.save(update_fields=['merged_into','updated_at'])
                    event(canonical,'merge-request:'+str(enquiry.request_id),'request_connected','Email-verified trial enquiry connected to signed-in account',request.user)
            sync_conversion(request.user.pk)
        return Response({'success':True})
