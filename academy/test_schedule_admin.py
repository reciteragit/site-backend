import json
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from .models import TeachingProfile, Slot, AvailabilitySchedule, Order, Booking
from .tests import fixture


class ScheduleAdminTests(TestCase):
    def setUp(self):
        self.student,self.teacher_user,self.profile,_,_,_=fixture()
        self.admin=get_user_model().objects.create_superuser('schedule-admin','admin@example.com','test-only-password')
        self.client.force_login(self.admin)
        day=timezone.now().date()+timedelta(days=5)
        self.data={'teacher':self.profile.pk,'kind':'class','timezone':'Africa/Cairo','start_date':day.isoformat(),'end_date':day.isoformat(),'duration_minutes':30,'weekly':json.dumps([{'day':d,'ranges':[{'start':'10:00','end':'12:00'}] if d==day.weekday() else []} for d in range(7)]),'_save':'Save'}

    def test_admin_calendar_editor_creates_and_changes_any_teacher_schedule_safely(self):
        url='/admin/academy/availabilityschedule/add/'
        response=self.client.get(url,{'teacher':self.profile.pk})
        self.assertContains(response,'data-weekly-editor')
        self.assertContains(response,'academy/weekly-hours.')
        response=self.client.post(url,self.data)
        self.assertEqual(response.status_code,302, response.context['adminform'].form.errors if response.status_code==200 else '')
        schedule=AvailabilitySchedule.objects.get(teacher=self.profile,kind='class')
        generated=list(schedule.slots.order_by('starts_at'))
        self.assertEqual(len(generated),4)
        order=Order.objects.create(request_id=__import__('uuid').uuid4(),user=self.student,email=self.student.email,status='paid',mode='test',amount=30,expires_at=timezone.now()+timedelta(days=2))
        booking=Booking.objects.create(order=order,slot=generated[0],student=self.student,teacher_name='Teacher',student_timezone='UTC',teacher_timezone='Africa/Cairo',meeting_url='https://lms.recitera.com',amount=30,status='confirmed')
        data={**self.data,'weekly':json.dumps([{'day':d,'ranges':[]} for d in range(7)])}
        data.pop('teacher');data.pop('kind')
        response=self.client.post(f'/admin/academy/availabilityschedule/{schedule.pk}/change/',data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(schedule.slots.filter(active=True).count(),1)
        generated[0].refresh_from_db();self.assertTrue(generated[0].active)
        booking.refresh_from_db();self.assertEqual(booking.status,'confirmed')
        self.assertEqual(AvailabilitySchedule.objects.count(),1)

    def test_invalid_or_oversized_plan_is_form_error_without_mutations(self):
        data={**self.data,'weekly':json.dumps([{'day':d,'ranges':[{'start':'12:00','end':'10:00'}]} for d in range(7)])}
        response=self.client.post('/admin/academy/availabilityschedule/add/',data)
        self.assertEqual(response.status_code,200)
        self.assertFalse(AvailabilitySchedule.objects.exists())
        self.assertEqual(Slot.objects.count(),1)

    def test_teacher_is_not_allowed_into_admin_editor(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get('/admin/academy/availabilityschedule/add/').status_code,302)
        staff=get_user_model().objects.create_user('restricted-staff',is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get('/admin/academy/availabilityschedule/add/').status_code,403)
