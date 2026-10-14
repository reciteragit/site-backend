import json, re
from datetime import date
from pathlib import Path
from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .forms import FormThrottle
from .models import TeacherApplication, TeacherAttachment

OPTIONS = json.loads((Path(__file__).parent/'teacher-options.json').read_text())
SPECIALTIES = ['Tajweed','Voice & Melody (Tarteel / Maqamat)','Memorization (Hifz)','Teaching Kids']
class TeacherApplicationSerializer(serializers.ModelSerializer):
    request_id = serializers.UUIDField()
    country = serializers.ChoiceField(choices=[o['value'] for o in OPTIONS['countries']])
    timezone = serializers.ChoiceField(choices=[o['value'] for o in OPTIONS['timezones']])
    whatsapp = serializers.RegexField(re.compile(r'^[+0-9() .#*=\-]{6,40}$'), max_length=40)
    years_of_experience = serializers.IntegerField(min_value=0,max_value=100)
    specializations = serializers.ListField(child=serializers.ChoiceField(choices=SPECIALTIES),max_length=4,required=False,default=list)
    languages = serializers.ListField(child=serializers.ChoiceField(choices=['English','Arabic','Other']),max_length=3,required=False,default=list)
    preferences = serializers.CharField(max_length=5000,allow_blank=True,required=False,default='')
    class Meta:
        model = TeacherApplication
        fields = ['request_id','first_name','last_name','nickname','gender','date_of_birth','whatsapp','years_of_experience','email','country','timezone','specializations','languages','other_languages','referral','preferences','sample_url']
    def validate_date_of_birth(self,value):
        if value>date.today():raise serializers.ValidationError('Date of birth cannot be in the future.')
        return value
    def validate_sample_url(self,value):
        if value and not value.startswith('https://'):raise serializers.ValidationError('Use an HTTPS link.')
        return value
    def validate(self,attrs):
        if 'Other' in attrs.get('languages',[]) and not attrs.get('other_languages','').strip():raise serializers.ValidationError({'other_languages':'Please specify your teaching languages.'})
        return attrs

def attachment(file,category):
    data=file.read()
    if not data or len(data)>3*1024*1024:raise ValueError('Invalid attachment size.')
    name=Path(file.name.replace('\\','/')).name[:200]
    ext=Path(name).suffix.lower()
    kind=None
    if ext=='.pdf' and data.startswith(b'%PDF-'):kind='application/pdf'
    elif ext in ['.jpg','.jpeg'] and data.startswith(b'\xff\xd8\xff'):kind='image/jpeg'
    elif ext=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n'):kind='image/png'
    elif category=='sample_work' and ext=='.mp4' and data[4:8]==b'ftyp':kind='video/mp4'
    elif category=='sample_work' and ext=='.webm' and data.startswith(b'\x1a\x45\xdf\xa3'):kind='video/webm'
    if not kind or (category=='profile_picture' and not kind.startswith('image/')):raise ValueError('Unsupported attachment. Use PDF, JPG or PNG; sample work also accepts MP4 or WebM.')
    return {'category':category,'filename':name,'content_type':kind,'size':len(data),'data':data}

class TeacherRegistration(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    throttle_classes=[FormThrottle]
    parser_classes=[MultiPartParser,FormParser]
    def post(self,request):
        serializer=TeacherApplicationSerializer(data=request.data)
        if not serializer.is_valid():return Response({'error':'Please check your application details.','fields':serializer.errors},status=400)
        groups={name:request.FILES.getlist(name) for name in ['sample_work','certificate','profile_picture']}
        files=[(name,f) for name,items in groups.items() for f in items]
        if len(groups['profile_picture'])!=1 or (not groups['sample_work'] and not serializer.validated_data.get('sample_url')):return Response({'error':'A profile picture and sample work or sample link are required.'},status=400)
        if len(files)>9 or sum(f.size for _,f in files)>3*1024*1024:return Response({'error':'Combined attachments must be 3 MB or less, with at most 9 files.'},status=413)
        try:attachments=[attachment(f,name) for name,f in files]
        except ValueError as e:return Response({'error':str(e)},status=400)
        values=dict(serializer.validated_data);key=values.pop('request_id')
        with transaction.atomic():
            application,created=TeacherApplication.objects.get_or_create(request_id=key,defaults=values)
            if created:TeacherAttachment.objects.bulk_create([TeacherAttachment(application=application,**f) for f in attachments])
        return Response({'success':True},status=201)
