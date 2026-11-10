import io
from decimal import Decimal
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from catalog.models import Teacher, TeacherApplication
from catalog.management.commands.publish_requested_teachers import REQUESTED


class PublishRequestedTeachersTests(TestCase):
    def test_import_uses_latest_forms_no_photos_and_preserves_admin_edits(self):
        for name, slug in REQUESTED:
            first, last = name.split(' ', 1)
            TeacherApplication.objects.create(first_name=first,last_name=last,email='private@example.com',whatsapp='+123456789',years_of_experience=3,country='Canada',timezone='America/Vancouver',specializations=['Tajweed'],languages=['English'],preferences='Private application note')
        TeacherApplication.objects.create(full_name='  MUHAMMAD   SHAFI ',email='latest@example.com',whatsapp='+123456789',years_of_experience=7,country='Canada',languages=['Arabic'])
        call_command('publish_requested_teachers',stdout=io.StringIO())
        self.assertEqual(Teacher.objects.count(),5)
        for teacher in Teacher.objects.all():
            self.assertEqual(teacher.price,Decimal('30'));self.assertEqual(teacher.currency,'CAD')
            self.assertEqual(teacher.image,'/assets/teacher-placeholder.svg');self.assertTrue(teacher.published)
            for private in ['private@example.com','latest@example.com','+123456789','Private application note']:
                self.assertNotIn(private,teacher.biography)
        teacher=Teacher.objects.get(slug='muhammad-shafi');self.assertEqual(teacher.experience,'7 years');self.assertEqual(teacher.languages,['Arabic'])
        teacher.price=42;teacher.save()
        call_command('publish_requested_teachers',stdout=io.StringIO())
        teacher.refresh_from_db();self.assertEqual(teacher.price,42);self.assertEqual(Teacher.objects.count(),5)
        self.assertFalse(get_user_model().objects.exists())

    def test_missing_applications_do_not_create_invented_profiles(self):
        output=io.StringIO();call_command('publish_requested_teachers',stdout=output)
        self.assertEqual(Teacher.objects.count(),0)
        self.assertIn('No saved application matched',output.getvalue())
