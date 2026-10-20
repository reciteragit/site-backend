import io
import json
import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase
from catalog.models import Teacher
from academy.models import TeachingProfile

User = get_user_model()

class TeacherAccountImportTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(slug='import-teacher', name='Teacher', price=30, languages=['English'])
        self.payload = {'batch': 'owned-test-import', 'initial_password': '12345678', 'teachers': [{'email': 'teacher@example.com', 'slug': self.teacher.slug}]}

    def run_import(self):
        with patch.dict(os.environ, {'TEACHER_ACCOUNTS_IMPORT_JSON': json.dumps(self.payload)}):
            call_command('import_teacher_accounts', stdout=io.StringIO())

    def test_links_login_and_rerun_preserves_new_password_and_schedule_settings(self):
        self.run_import()
        user = User.objects.get(email='teacher@example.com')
        self.assertTrue(user.check_password('12345678'))
        profile = TeachingProfile.objects.get(user=user)
        self.assertEqual(profile.teacher, self.teacher)
        self.assertTrue(profile.approved)
        user.set_password('A-new-private-password-57!'); user.save()
        profile.timezone = 'America/Toronto'; profile.meeting_url = 'https://meet.google.com/abc-defg-hij'; profile.save()
        self.run_import()
        user.refresh_from_db(); profile.refresh_from_db()
        self.assertTrue(user.check_password('A-new-private-password-57!'))
        self.assertEqual(profile.timezone, 'America/Toronto')
        self.assertEqual(profile.meeting_url, 'https://meet.google.com/abc-defg-hij')

    def test_conflict_rolls_back_entire_batch(self):
        self.payload['teachers'].append({'email': 'missing@example.com', 'slug': 'zz-missing'})
        with self.assertRaises(CommandError): self.run_import()
        self.assertFalse(User.objects.filter(email='teacher@example.com').exists())
        self.assertFalse(TeachingProfile.objects.exists())

    def test_does_not_reset_staff_password(self):
        user = User.objects.create_user(username='admin', email='teacher@example.com', password='Original-password-75!', is_staff=True)
        with self.assertRaises(CommandError): self.run_import()
        user.refresh_from_db()
        self.assertTrue(user.check_password('Original-password-75!'))
