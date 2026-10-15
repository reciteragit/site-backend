import uuid
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from .models import ScholarshipApplication

class ScholarshipTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.data = {'request_id':str(uuid.uuid4()),'name':'Test Learner','email':'learner@example.com','whatsapp':'+1 555 123 4567','message':'Learning support for my child.'}
    def test_save_retry_and_admin_review(self):
        for _ in range(2):
            response=self.client.post('/api/forms/scholarship/',self.data,format='json')
            self.assertEqual(response.status_code,201)
            self.assertEqual(response.json(),{'success':True})
        item=ScholarshipApplication.objects.get()
        self.assertEqual(item.message,self.data['message'])
        self.assertEqual(item.whatsapp,self.data['whatsapp'])
        self.assertFalse(item.reviewed)
        admin=User.objects.create_superuser('scholarship-admin','admin@example.com','test-password')
        self.client.force_login(admin)
        response=self.client.get(reverse('admin:catalog_scholarshipapplication_changelist'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Test Learner')
    def test_invalid_data_never_stored(self):
        for field,value in [('email','bad'),('whatsapp','abc'),('name',''),('message','x'*5001),('request_id','bad')]:
            self.assertEqual(self.client.post('/api/forms/scholarship/',{**self.data,field:value},format='json').status_code,400)
        self.assertEqual(ScholarshipApplication.objects.count(),0)
    def test_details_optional_and_no_public_listing(self):
        data={**self.data};data.pop('message')
        self.assertEqual(self.client.post('/api/forms/scholarship/',data,format='json').status_code,201)
        self.assertEqual(self.client.get('/api/forms/scholarship/').status_code,405)
        self.assertEqual(self.client.get(reverse('admin:catalog_scholarshipapplication_changelist')).status_code,302)
