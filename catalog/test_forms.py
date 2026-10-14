import uuid
from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient
from .models import VolunteerApplication, NewsletterSubscriber

class FormTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
    def test_volunteer_is_persisted_and_retry_is_idempotent(self):
        body={'request_id':str(uuid.uuid4()),'name':'Test Learner','email':'test@example.com','whatsapp':'+123456789','areas':['Translation','Research'],'message':'Skills'}
        for _ in range(2):self.assertEqual(self.client.post('/api/forms/volunteer/',body,format='json').status_code,201)
        self.assertEqual(VolunteerApplication.objects.count(),1)
        self.assertEqual(VolunteerApplication.objects.get().areas,['Translation','Research'])
    def test_invalid_submission_is_not_saved(self):
        self.assertEqual(self.client.post('/api/forms/volunteer/',{'email':'bad'},format='json').status_code,400)
        self.assertEqual(VolunteerApplication.objects.count(),0)
    def test_subscriber_is_normalized_and_private(self):
        for email in ['TEST@example.com','test@example.com']:
            self.assertEqual(self.client.post('/api/forms/newsletter/',{'email':email},format='json').status_code,201)
        self.assertEqual(NewsletterSubscriber.objects.count(),1)
        self.assertEqual(self.client.get('/api/forms/newsletter/').status_code,405)
        self.assertEqual(self.client.get('/api/forms/volunteer/').status_code,405)
