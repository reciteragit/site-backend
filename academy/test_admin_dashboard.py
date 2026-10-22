from datetime import timedelta
import uuid
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from catalog.models import Teacher, TeacherApplication
from .models import Profile, Order, Slot, Booking, TeachingProfile
from .tests import fixture


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.student,self.teacher_user,self.teacher,self.slot,self.config,self.api=fixture()
        self.owner=get_user_model().objects.create_superuser('admin-preview','admin@example.com','Example-password-72!')
        Profile.objects.create(user=self.owner,timezone='Asia/Tehran')
        self.client.force_login(self.owner)

    def order(self,amount,mode='live',status='paid',currency='CAD'):
        return Order.objects.create(user=self.student,email=self.student.email,request_id=uuid.uuid4(),amount=amount,mode=mode,status=status,currency=currency,expires_at=timezone.now()+timedelta(hours=1),paid_at=timezone.now() if status=='paid' else None)

    def test_dashboard_uses_real_live_revenue_and_keeps_currencies_separate(self):
        self.order(30);self.order(10,mode='test');self.order(90,status='held');self.order(12,currency='EUR')
        response=self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code,200)
        dashboard=response.context['dashboard']
        self.assertEqual(dashboard['metrics'][0]['value'],'30.00 CAD · 12.00 EUR')
        self.assertEqual(dashboard['zone'],'Asia/Tehran')
        self.assertContains(response,'Academy overview')
        self.assertContains(response,'recitera/admin.')
        self.assertNotContains(response,'sk_test_fixture')
        # Refreshing overview must not alter payment or booking state.
        self.assertEqual(Order.objects.filter(status='held').count(),1)

    def test_staff_dashboard_does_not_leak_data_without_model_permissions(self):
        staff=get_user_model().objects.create_user('reviewer','reviewer@example.com',is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='catalog',codename='view_teacher'))
        self.client.force_login(staff)
        response=self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code,200)
        dashboard=response.context['dashboard']
        self.assertEqual([metric['label'] for metric in dashboard['metrics']],['Published teachers'])
        self.assertFalse(dashboard['can_view_bookings'])
        self.assertFalse(dashboard['can_view_applications'])
        self.assertEqual(dashboard['attention'],[])
        self.assertNotContains(response,'Payments received')
        self.assertNotContains(response,self.student.email)
        self.assertNotContains(response,'Stripe connection')
        self.assertEqual(self.client.get(reverse('admin:academy_order_changelist')).status_code,403)

    def test_model_pages_and_dashboard_filter_links_render(self):
        order=self.order(30)
        booking=Booking.objects.create(order=order,student=self.student,slot=self.slot,student_timezone='Asia/Tehran',teacher_timezone='America/Toronto',teacher_name=self.teacher.teacher.name,amount=30,status='confirmed',meeting_url=self.teacher.meeting_url)
        application=TeacherApplication.objects.create(full_name='Example applicant',email='applicant@example.com',whatsapp='+100000000',preferences='Example')
        for model,model_admin in admin.site._registry.items():
            with self.subTest(model=model._meta.label,view='list'):
                self.assertEqual(self.client.get(reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_changelist')).status_code,200)
            if model_admin.has_add_permission(type('Request',(),{'user':self.owner})()):
                with self.subTest(model=model._meta.label,view='add'):
                    self.assertEqual(self.client.get(reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_add')).status_code,200)
        for obj in [self.teacher.teacher,self.teacher,self.owner,self.config,order,booking,application]:
            with self.subTest(change=obj._meta.label):
                self.assertEqual(self.client.get(reverse(f'admin:{obj._meta.app_label}_{obj._meta.model_name}_change',args=[obj.pk])).status_code,200)
        response=self.client.get(reverse('admin:index'))
        for entry in response.context['dashboard']['metrics']+response.context['dashboard']['attention']:
            with self.subTest(link=entry['url']):
                self.assertEqual(self.client.get(entry['url']).status_code,200)
        self.assertEqual(response.context['dashboard']['bookings'][0]['starts_at'].utcoffset(),timedelta(hours=3,minutes=30))
        self.assertEqual(len(response.context['dashboard']['activity']),7)
        self.assertFalse(admin.site._registry[Order].has_add_permission(type('Request',(),{'user':self.owner})()))

    def test_anonymous_admin_redirects_to_branded_login(self):
        self.client.logout()
        response=self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code,302)
        self.assertIn('/admin/login/',response['Location'])
        self.assertContains(self.client.get(reverse('admin:login')),'Recitera Admin')

    def test_admin_login_returns_to_dashboard_and_preserves_deep_link(self):
        self.client.logout()
        response=self.client.post(reverse('admin:login'),{'username':self.owner.username,'password':'Example-password-72!'},follow=False)
        self.assertRedirects(response,reverse('admin:index'),fetch_redirect_response=False)
        self.client.logout()
        target=reverse('admin:catalog_teacher_changelist')
        response=self.client.post(reverse('admin:login'),{'username':self.owner.username,'password':'Example-password-72!','next':target},follow=False)
        self.assertRedirects(response,target,fetch_redirect_response=False)

    def test_stripe_settings_never_render_stored_secrets(self):
        response=self.client.get(reverse('admin:catalog_stripesettings_change',args=[self.config.pk]))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'sk_test_fixture')
        self.assertNotContains(response,'whsec_fixture')
        self.assertContains(response,'type="password"')

    def test_short_teacher_application_can_be_reviewed_without_inventing_legacy_data(self):
        from django.test import RequestFactory
        request=RequestFactory().get('/admin/');request.user=self.owner
        application=TeacherApplication.objects.create(full_name='Example applicant',email='applicant@example.com',whatsapp='+100000000',preferences='Sample description')
        form_class=admin.site._registry[TeacherApplication].get_form(request,application)
        form=form_class(data={'full_name':application.full_name,'email':application.email,'whatsapp':application.whatsapp,'preferences':application.preferences,'reviewed':'on'},instance=application)
        self.assertTrue(form.is_valid(),form.errors)
        saved=form.save()
        self.assertTrue(saved.reviewed)
        self.assertFalse(saved.languages)

    def test_invalid_period_uses_safe_default(self):
        self.assertEqual(self.client.get(reverse('admin:index')+'?period=anything').context['dashboard']['days'],30)
        self.assertEqual(self.client.get(reverse('admin:index')+'?period=7').context['dashboard']['days'],7)
