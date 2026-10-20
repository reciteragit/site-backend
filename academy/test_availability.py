from datetime import datetime, timedelta, timezone as utc
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from catalog.models import Teacher
from academy.availability import ScheduleInput, save_schedule
from academy.authentication import issue_token
from academy.models import TeachingProfile, AvailabilitySchedule, Slot, Booking, Order

NOW = datetime(2026, 10, 20, 12, tzinfo=utc.utc)

class WeeklyAvailabilityTests(TestCase):
    def setUp(self):
        self.clock = patch('django.utils.timezone.now', return_value=NOW); self.clock.start(); self.addCleanup(self.clock.stop)
        self.user = get_user_model().objects.create_user(username='schedule-teacher', email='schedule@example.com')
        teacher = Teacher.objects.create(slug='schedule-teacher', name='Schedule teacher', price=30, published=True, languages=['English'])
        self.profile = TeachingProfile.objects.create(user=self.user, teacher=teacher, approved=True)
        self.api = APIClient(); self.api.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(self.user))

    def data(self, start='2026-10-26', end='2026-11-02', tz='Europe/Paris', day=0, begin='19:30', finish='20:30'):
        return {'timezone': tz, 'start_date': start, 'end_date': end, 'duration_minutes': 30, 'weekly': [{'day': d, 'ranges': [{'start': begin, 'end': finish}] if d == day else []} for d in range(7)]}

    def save(self, data):
        s = ScheduleInput(data=data); s.is_valid(raise_exception=True)
        return save_schedule(self.profile, dict(s.validated_data))

    def test_local_weekly_recurrence_splits_complete_classes_across_dst(self):
        result = self.save(self.data(start='2026-10-23', end='2026-10-30', day=4))
        self.assertEqual(result['created'], 4)
        slots = list(Slot.objects.order_by('starts_at'))
        self.assertEqual(slots[0].starts_at.isoformat(), '2026-10-23T17:30:00+00:00')
        self.assertEqual(slots[2].starts_at.isoformat(), '2026-10-30T18:30:00+00:00')
        self.assertTrue(all(s.ends_at - s.starts_at == timedelta(minutes=30) for s in slots))
        self.profile.refresh_from_db(); self.assertEqual(self.profile.timezone, 'Europe/Paris')

    def test_repeated_save_keeps_ids_and_no_duplicates(self):
        self.save(self.data()); ids = set(Slot.objects.values_list('id', flat=True))
        result = self.save(self.data()); self.assertEqual(result['created'], 0)
        self.assertEqual(set(Slot.objects.values_list('id', flat=True)), ids)

    def test_edit_preserves_reserved_and_manual_slots(self):
        self.save(self.data()); reserved = Slot.objects.first()
        order = Order.objects.create(user=self.user, email=self.user.email, amount=30, mode='test', expires_at=NOW+timedelta(days=10), request_id=__import__('uuid').uuid4())
        Booking.objects.create(order=order, slot=reserved, student=self.user, student_timezone='UTC', teacher_timezone='Europe/Paris', teacher_name='Teacher', amount=30, meeting_url='https://lms.recitera.com/', status='confirmed')
        manual = Slot.objects.create(teacher=self.profile, starts_at=datetime(2026,10,27,18,tzinfo=utc.utc), ends_at=datetime(2026,10,27,18,30,tzinfo=utc.utc))
        result = self.save(self.data(begin='20:00', finish='21:00'))
        reserved.refresh_from_db(); manual.refresh_from_db()
        self.assertTrue(reserved.active); self.assertTrue(manual.active)
        self.assertEqual(result['preserved_reserved'], 1)
        self.assertEqual(Slot.objects.filter(active=True, starts_at=datetime(2026,10,26,19,tzinfo=utc.utc)).count(), 1)
        self.assertFalse(Slot.objects.filter(schedule__isnull=False,active=True,starts_at__lt=reserved.ends_at,ends_at__gt=reserved.starts_at).exclude(pk=reserved.pk).exists())

    def test_overlapping_manual_class_is_skipped_without_deleting_it(self):
        manual = Slot.objects.create(teacher=self.profile, starts_at=datetime(2026,10,26,18,45,tzinfo=utc.utc), ends_at=datetime(2026,10,26,19,15,tzinfo=utc.utc))
        result = self.save(self.data()); self.assertEqual(result['skipped_overlap'], 2)
        manual.refresh_from_db(); self.assertTrue(manual.active)

    def test_dst_missing_times_are_reported_and_not_shifted(self):
        # Spring-forward gap in Paris on Sunday 28 March 2027, within 180 days.
        result = self.save(self.data(start='2027-03-28', end='2027-03-28', day=6, begin='01:30', finish='04:00'))
        self.assertGreater(result['skipped_dst'], 0)
        self.assertTrue(all(s.ends_at-s.starts_at == timedelta(minutes=30) for s in Slot.objects.all()))

    def test_invalid_ranges_and_bounds_are_rejected_without_writes(self):
        values = [self.data(begin='20:00',finish='19:00'),self.data(end='2027-10-20'),self.data(start='2026-10-19')]
        overlapping = self.data();overlapping['weekly'][0]['ranges'].append({'start':'20:00','end':'21:00'});values.append(overlapping)
        for data in values:
            with self.assertRaises(ValidationError): self.save(data)
        self.assertFalse(AvailabilitySchedule.objects.exists());self.assertFalse(Slot.objects.exists())

    def test_public_date_and_slot_queries_use_student_local_day(self):
        self.save(self.data(start='2026-10-26',end='2026-10-26',tz='America/Toronto',begin='21:00',finish='22:00'))
        public = APIClient(); root='/api/academy/teachers/schedule-teacher/'
        result=public.get(root+'availability/',{'timezone':'Asia/Tehran'})
        self.assertEqual(result.data['dates'],['2026-10-27'])
        self.assertEqual(len(public.get(root+'slots/',{'date':'2026-10-27','timezone':'Asia/Tehran'}).data),2)
        self.assertEqual(public.get(root+'slots/',{'date':'2026-10-26','timezone':'Asia/Tehran'}).data,[])
        self.profile.approved=False; self.profile.save()
        self.assertEqual(public.get(root+'availability/',{'timezone':'Asia/Tehran'}).data['dates'],[])

    def test_teacher_endpoint_auth_and_persistence(self):
        self.assertEqual(self.api.get('/api/academy/teacher/availability/').data, {'schedule': None})
        self.assertEqual(APIClient().post('/api/academy/teacher/availability/',self.data(),format='json').status_code,401)
        response=self.api.post('/api/academy/teacher/availability/',self.data(),format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.api.get('/api/academy/teacher/availability/').data['schedule']['timezone'],'Europe/Paris')
