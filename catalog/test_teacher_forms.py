import uuid
from django.test import TestCase
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from .models import TeacherApplication, TeacherAttachment

class TeacherRegistrationTests(TestCase):
    def setUp(self):
        cache.clear();self.client=APIClient();self.key=str(uuid.uuid4())
    def payload(self):
        return {'request_id':self.key,'first_name':'Test','last_name':'Teacher','gender':'Other','date_of_birth':'1990-01-01','whatsapp':'+123456789','years_of_experience':4,'email':'test@example.com','country':'Canada','timezone':'America/Toronto','specializations':['Tajweed','Teaching Kids'],'languages':['English'],'sample_url':'https://example.com/video','profile_picture':SimpleUploadedFile('profile.png',b'\x89PNG\r\n\x1a\nfixture',content_type='image/png'),'certificate':SimpleUploadedFile('certificate.pdf',b'%PDF-1.7 fixture',content_type='application/pdf')}
    def test_persistence_attachments_and_idempotency(self):
        for _ in range(2):self.assertEqual(self.client.post('/api/forms/teacher/',self.payload(),format='multipart').status_code,201)
        self.assertEqual(TeacherApplication.objects.count(),1)
        application=TeacherApplication.objects.get()
        self.assertEqual(application.specializations,['Tajweed','Teaching Kids'])
        self.assertEqual(application.languages,['English'])
        self.assertEqual(application.attachments.count(),2)
    def test_sample_work_is_required(self):
        body=self.payload();body['sample_url']='';self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400)
        self.assertFalse(TeacherApplication.objects.exists())
    def test_disguised_unsafe_file_rejected(self):
        body=self.payload();body['profile_picture']=SimpleUploadedFile('photo.png',b'<script>unsafe</script>',content_type='image/png')
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400)
        self.assertFalse(TeacherAttachment.objects.exists())
    def test_large_files_rejected(self):
        body=self.payload();body['profile_picture']=SimpleUploadedFile('photo.png',b'\x89PNG\r\n\x1a\n'+b'x'*(3*1024*1024))
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,413)
    def test_other_language_requires_details(self):
        body=self.payload();body['languages']=['Other']
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400)
    def test_attachments_only_available_to_admin(self):
        self.client.post('/api/forms/teacher/',self.payload(),format='multipart')
        item=TeacherAttachment.objects.first();url=reverse('admin:teacher_attachment_download',args=[item.application_id,item.pk])
        self.assertEqual(self.client.get(url).status_code,302)
        get_user_model().objects.create_superuser('testadmin','admin@example.com','Local-test-password-123')
        self.client.login(username='testadmin',password='Local-test-password-123')
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment',response['Content-Disposition'])
        self.assertIn('private',response['Cache-Control'])
        self.assertIn('no-store',response['Cache-Control'])
    def test_no_public_read_endpoint(self):
        self.assertEqual(self.client.get('/api/forms/teacher/').status_code,405)

class ShortTeacherApplicationTests(TestCase):
    def setUp(self):
        cache.clear();self.client=APIClient()
        self.data={'request_id':str(uuid.uuid4()),'full_name':'آزمایش نام خانوادگی','email':'short-form@example.com','whatsapp':'+1234567890','description':'I teach Quran recitation.'}
    def test_four_field_application_persists_without_documents_and_retries_once(self):
        for _ in range(2):self.assertEqual(self.client.post('/api/forms/teacher/',self.data,format='multipart').status_code,201)
        self.assertEqual(TeacherApplication.objects.count(),1)
        application=TeacherApplication.objects.get()
        self.assertEqual(application.full_name,self.data['full_name']);self.assertEqual(str(application),self.data['full_name'])
        self.assertEqual(application.preferences,self.data['description'])
        self.assertIsNone(application.date_of_birth);self.assertIsNone(application.years_of_experience)
        self.assertFalse(application.attachments.exists());self.assertFalse(application.reviewed)
    def test_required_fields_and_invalid_email_or_whatsapp_are_rejected(self):
        for field in ['full_name','email','whatsapp','description']:
            body=dict(self.data);body[field]=''
            self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400)
        for field,value in [('email','invalid'),('whatsapp','not-a-phone')]:
            body=dict(self.data);body[field]=value
            self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400)
        self.assertFalse(TeacherApplication.objects.exists())
    def test_cannot_set_reviewed_flag(self):
        body=dict(self.data,reviewed=True)
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,201)
        self.assertFalse(TeacherApplication.objects.get().reviewed)

class ProfileTeacherApplicationTests(TestCase):
    def setUp(self):cache.clear();self.client=APIClient();self.key=str(uuid.uuid4())
    def payload(self):
        return {'request_id':self.key,'form_version':'profile_v2','first_name':'Test','last_name':'Teacher','nickname':'','gender':'Female','date_of_birth':'1991-06-12','whatsapp':'+15551234567','years_of_experience':3,'email':'applicant@example.com','country':'Canada','timezone':'America/Vancouver','specializations':['Tajweed','Teaching Kids'],'languages':['English','Persian'],'referral':'Search','preferences':'I teach beginners','profile_picture':SimpleUploadedFile('portrait.png',b'\x89PNG\r\n\x1a\nfixture',content_type='image/png')}
    def test_photo_only_application_persists_questions_and_is_idempotent(self):
        for _ in range(2):
            response=self.client.post('/api/forms/teacher/',self.payload(),format='multipart')
            self.assertEqual(response.status_code,201,response.data)
        row=TeacherApplication.objects.get()
        self.assertEqual(row.languages,['English','Persian']);self.assertEqual(row.timezone,'America/Vancouver')
        self.assertEqual(row.specializations,['Tajweed','Teaching Kids']);self.assertEqual(row.referral,'Search')
        self.assertEqual(row.attachments.count(),1);self.assertEqual(row.attachments.get().category,'profile_picture')
        self.assertFalse(row.sample_url);self.assertFalse(row.reviewed)
    def test_missing_photo_required_questions_and_unsafe_photo_rejected(self):
        for field in ['profile_picture','first_name','last_name','gender','date_of_birth','years_of_experience','country','timezone','specializations','languages']:
            cache.clear();body=self.payload();body.pop(field)
            self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400,field)
        cache.clear();body=self.payload();body['profile_picture']=SimpleUploadedFile('portrait.png',b'<script>invalid</script>',content_type='image/png')
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,400)
        self.assertFalse(TeacherApplication.objects.exists())

    def test_new_request_cannot_repeat_email_or_normalized_phone(self):
        self.assertEqual(self.client.post('/api/forms/teacher/',self.payload(),format='multipart').status_code,201)
        for email,phone in [('APPLICANT@example.com','+447123456789'),('different@example.com','001 (555) 123-4567')]:
            body=self.payload();body.update(request_id=str(uuid.uuid4()),email=email,whatsapp=phone)
            response=self.client.post('/api/forms/teacher/',body,format='multipart')
            self.assertEqual(response.status_code,409,response.data)
            self.assertIn('support team will contact you',response.data['error'])
        self.assertEqual(TeacherApplication.objects.count(),1)
        self.assertEqual(TeacherAttachment.objects.count(),1)
        body=self.payload();body.update(request_id=str(uuid.uuid4()),email='another@example.com',whatsapp='+447999123456')
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,201)

    def test_legacy_short_form_cannot_bypass_duplicate_check(self):
        self.client.post('/api/forms/teacher/',self.payload(),format='multipart')
        body={'request_id':str(uuid.uuid4()),'full_name':'Test Teacher','email':'applicant@example.com','whatsapp':'+447123456789','description':'Teaching application'}
        self.assertEqual(self.client.post('/api/forms/teacher/',body,format='multipart').status_code,409)
        self.assertEqual(TeacherApplication.objects.count(),1)
