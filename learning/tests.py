from datetime import timedelta
from decimal import Decimal
import hashlib,hmac,json,time,uuid
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from academy.tests import fixture
from catalog.models import Course
from catalog.payment_models import PaymentOrder
from catalog.discount_models import DiscountCode
from .models import Episode,CourseBundle,Enrollment,EpisodeProgress,CoursePurchase,vimeo_embed,validate_video_url


class LearningTests(TestCase):
    def setUp(self):
        self.user,_,self.teacher,_,self.config,self.api=fixture()
        self.config.courses_enabled=True;self.config.save()
        self.course=Course.objects.create(slug='quran-basics',title='Quran basics',description='A recorded course',teacher=self.teacher.teacher,price=100,delivery_mode='platform')
        self.intro=Episode.objects.create(course=self.course,title='Introduction',video_provider='direct',video_url='https://cdn.example.org/intro.mp4',is_free=True,duration_seconds=60)
        self.paid=Episode.objects.create(course=self.course,title='Practice',video_provider='vimeo',video_url='https://vimeo.com/123456789/abc123',duration_seconds=120)
        self.guest=APIClient()
    def data(self,purpose='course',reference=None,**extra):
        return {'request_id':str(uuid.uuid4()),'purpose':purpose,'reference':reference or self.course.slug,'email':'someone-else@example.com','first_name':'Untrusted',**extra}
    def gateway(self):
        return SimpleNamespace(id='cs_learning',url='https://checkout.stripe.com/c/pay/learning',livemode=False,expires_at=int(time.time())+3600)
    def pay(self,data=None):
        with patch('catalog.payments.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.return_value=self.gateway()
            response=self.api.post('/api/payments/checkout/',data or self.data(),format='json')
            self.assertEqual(response.status_code,200,response.data)
            return PaymentOrder.objects.get(pk=response.data['order_id'])
    def webhook(self,order,amount=None,event_id=None):
        event={'id':event_id or 'evt_'+uuid.uuid4().hex,'type':'checkout.session.completed','livemode':False,'data':{'object':{'id':order.stripe_session_id,'metadata':{'order_id':str(order.pk)},'amount_total':int(order.amount*100) if amount is None else amount,'currency':'cad','payment_status':'paid','payment_intent':'pi_learning'}}}
        body=json.dumps(event).encode();stamp=int(time.time());signature=hmac.new(b'whsec_fixture',str(stamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
        return self.guest.post('/api/payments/stripe/webhook/',body,content_type='application/json',HTTP_STRIPE_SIGNATURE=f't={stamp},v1={signature}')
    def test_public_metadata_never_exposes_paid_video_urls(self):
        response=self.guest.get(f'/api/academy/learning/courses/{self.course.slug}/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'vimeo.com');self.assertNotContains(response,'abc123');self.assertNotContains(response,'cdn.example.org')
        self.assertTrue(response.data['episodes'][0]['accessible']);self.assertFalse(response.data['episodes'][1]['accessible'])
        self.assertEqual(self.guest.get(f'/api/academy/learning/episodes/{self.paid.pk}/').status_code,403)
        preview=self.guest.get(f'/api/academy/learning/episodes/{self.intro.pk}/')
        self.assertEqual(preview.data['provider'],'direct');self.assertEqual(preview.data['playback_url'],self.intro.video_url)
    def test_purchase_requires_login_and_waits_for_signed_confirmation(self):
        self.assertEqual(self.guest.post('/api/payments/checkout/',self.data(),format='json').status_code,401)
        order=self.pay()
        self.assertEqual(order.buyer,self.user);self.assertEqual(order.donor.email,self.user.email)
        self.assertFalse(Enrollment.objects.exists())
        self.assertEqual(self.webhook(order,amount=1).status_code,400);self.assertFalse(Enrollment.objects.exists())
        self.assertEqual(self.webhook(order,event_id='evt_unique').status_code,200)
        self.assertEqual(self.webhook(order,event_id='evt_unique').status_code,200)
        self.assertEqual(Enrollment.objects.count(),1)
        video=self.api.get(f'/api/academy/learning/episodes/{self.paid.pk}/')
        self.assertEqual(video.status_code,200);self.assertIn('player.vimeo.com/video/123456789',video.data['playback_url']);self.assertIn('h=abc123',video.data['playback_url'])
        other=get_user_model().objects.create_user('other-student');self.guest.force_authenticate(other)
        self.assertEqual(self.guest.get(f'/api/academy/learning/episodes/{self.paid.pk}/').status_code,403)
    def test_free_enrolment_and_paid_preview_progress_do_not_grant_paid_access(self):
        self.assertEqual(self.api.post(f'/api/academy/learning/courses/{self.course.slug}/enroll/',{},format='json').status_code,403)
        response=self.api.post(f'/api/academy/learning/episodes/{self.intro.pk}/progress/',{'position_seconds':30,'duration_seconds':60,'watched_delta':15},format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertFalse(Enrollment.objects.exists())
        self.course.price=0;self.course.save()
        self.assertEqual(self.api.post(f'/api/academy/learning/courses/{self.course.slug}/enroll/',{},format='json').status_code,200)
        self.assertEqual(self.api.get('/api/academy/learning/library/').data[0]['slug'],self.course.slug)
    def test_full_discount_grants_course_without_stripe_and_retry_is_idempotent(self):
        DiscountCode.objects.create(code='FREECOURSE',name='Full course offer',value=100)
        data=self.data(discount_code='FREECOURSE')
        with patch('catalog.payments.client') as gateway:
            result=self.api.post('/api/payments/checkout/',data,format='json');self.assertEqual(result.status_code,200,result.data);gateway.assert_not_called()
        self.assertEqual(Enrollment.objects.count(),1)
        self.assertEqual(PaymentOrder.objects.get().mode,'free')
        self.assertEqual(self.api.post('/api/payments/checkout/',data,format='json').status_code,200)
        self.assertEqual(Enrollment.objects.count(),1)
    def test_bundle_discount_and_access_snapshot_survive_package_edits(self):
        second=Course.objects.create(slug='second',title='Second course',teacher=self.teacher.teacher,price=50,description='Second',delivery_mode='platform')
        Episode.objects.create(course=second,title='Second video',video_provider='direct',video_url='https://cdn.example.org/second.webm')
        bundle=CourseBundle.objects.create(slug='complete',title='Complete collection',discount_percent=20,published=True);bundle.courses.add(self.course,second)
        coupon=DiscountCode.objects.create(code='PACKAGE10',name='Package offer',discount_type='fixed',value=10,all_products=False);coupon.bundles.add(bundle)
        order=self.pay(self.data('bundle',bundle.slug,discount_code='PACKAGE10'))
        self.assertEqual(order.subtotal,Decimal('120'));self.assertEqual(order.amount,110)
        self.assertEqual(CoursePurchase.objects.filter(order=order).count(),2)
        bundle.courses.clear()
        self.assertEqual(self.webhook(order).status_code,200)
        self.assertEqual(Enrollment.objects.filter(user=self.user).count(),2)
    def test_progress_is_per_user_bounded_and_resumes_without_losing_completion(self):
        Enrollment.objects.create(user=self.user,course=self.course)
        path=f'/api/academy/learning/episodes/{self.paid.pk}/progress/'
        self.assertEqual(self.guest.post(path,{'position_seconds':120},format='json').status_code,401)
        response=self.api.post(path,{'position_seconds':999,'duration_seconds':999,'watched_delta':20,'completed':True},format='json')
        self.assertEqual(response.status_code,200,response.data);self.assertEqual(response.data['position_seconds'],120);self.assertTrue(response.data['completed'])
        self.api.post(path,{'position_seconds':10,'watched_delta':20},format='json')
        row=EpisodeProgress.objects.get();self.assertTrue(row.completed);self.assertLessEqual(row.watched_seconds,22)
        library=self.api.get('/api/academy/learning/library/').data[0];self.assertEqual(library['completed_count'],1);self.assertEqual(library['progress_percent'],50)
        self.assertEqual(self.api.get(f'/api/academy/learning/episodes/{self.paid.pk}/').data['progress']['position_seconds'],10)
    def test_unpublished_or_revoked_content_is_not_exposed(self):
        enrollment=Enrollment.objects.create(user=self.user,course=self.course)
        self.course.published=False;self.course.save()
        self.assertEqual(self.guest.get(f'/api/academy/learning/courses/{self.course.slug}/').status_code,404)
        self.assertEqual(self.api.get(f'/api/academy/learning/courses/{self.course.slug}/').status_code,200)
        enrollment.active=False;enrollment.save()
        self.assertEqual(self.api.get(f'/api/academy/learning/episodes/{self.paid.pk}/').status_code,403)
    def test_revoked_access_cannot_be_charged_again(self):
        Enrollment.objects.create(user=self.user,course=self.course,active=False)
        result=self.api.post('/api/payments/checkout/',self.data(),format='json')
        self.assertEqual(result.status_code,400)
        self.assertFalse(PaymentOrder.objects.exists())

    def test_vimeo_and_other_host_validation(self):
        for value in ['https://cdn.example.org/movie.mp4?token=example','https://storage.example.org/path/file.webm']:
            validate_video_url(value)
        for value in ['javascript:alert(1)','http://cdn.example.org/movie.mp4','https://user:password@example.org/video.mp4','https://127.0.0.1/video.mp4','https://localhost/video.mp4']:
            with self.assertRaises(ValidationError):validate_video_url(value)
        with self.assertRaises(ValidationError):vimeo_embed('https://vimeo.com.evil.example/123')
        with self.assertRaises(ValidationError):vimeo_embed('https://vimeo.com/123?h=bad%21')
