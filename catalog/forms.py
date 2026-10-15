import re
from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from .models import VolunteerApplication, NewsletterSubscriber, ScholarshipApplication

AREAS = ['Content & Social Media','Translation','Design & Video','Technology & Product','Marketing & Partnerships','Events & Community','Research','Other']
class FormThrottle(AnonRateThrottle):
    rate = '10/min'

class VolunteerSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    whatsapp = serializers.RegexField(re.compile(r'^[+0-9() .#*=\-]{6,40}$'), max_length=40)
    areas = serializers.ListField(child=serializers.ChoiceField(choices=AREAS), max_length=8, required=False, default=list)
    message = serializers.CharField(max_length=5000, allow_blank=True, required=False, default='')

class NewsletterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    def validate_email(self, value):
        return value.strip().lower()

class VolunteerRegistration(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FormThrottle]
    def post(self, request):
        serializer = VolunteerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        key = data.pop('request_id')
        with transaction.atomic():
            # Retried network requests must not create duplicate applications.
            VolunteerApplication.objects.get_or_create(request_id=key, defaults=data)
        return Response({'success': True}, status=201)

class NewsletterRegistration(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FormThrottle]
    def post(self, request):
        serializer = NewsletterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Do not disclose existing subscribers or reactivate opted-out addresses.
        NewsletterSubscriber.objects.get_or_create(email=serializer.validated_data['email'])
        return Response({'success': True}, status=201)

class ScholarshipSerializer(VolunteerSerializer):
    # Scholarship requests use the reference form's four fields.
    areas = None

class ScholarshipRegistration(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FormThrottle]
    def post(self, request):
        serializer = ScholarshipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        key = data.pop('request_id')
        with transaction.atomic():
            ScholarshipApplication.objects.get_or_create(request_id=key, defaults=data)
        return Response({'success': True}, status=201)
