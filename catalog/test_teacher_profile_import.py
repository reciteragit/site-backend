import importlib,json
from pathlib import Path
from decimal import Decimal
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.core.management import call_command
from rest_framework.test import APIClient
from catalog.models import Teacher
from academy.models import TeachingProfile

class UploadedTeacherProfileTests(TestCase):
    def test_new_catalogue_and_public_api_expose_full_profiles_without_fake_accounts(self):
        call_command('seed_catalog',verbosity=0)
        client=APIClient()
        rows=json.loads((Path(__file__).parent/'teacher_profiles_20261020.json').read_text())
        self.assertEqual(len(rows),6)
        for row in rows:
            teacher=Teacher.objects.get(slug=row['slug'])
            self.assertEqual(teacher.biography,row['biography'])
            result=client.get(f'/api/academy/teachers/{teacher.slug}/').json()
            for key in ['name','biography','based_in','specialities']:self.assertEqual(result[key],row[key])
            self.assertFalse(result['booking_enabled']);self.assertEqual(result['timezone'],'')
            self.assertNotIn('meeting_url',result)
        self.assertEqual(Teacher.objects.get(slug='fatima-abdulkazem').price,Decimal('20.00'))
        self.assertFalse(TeachingProfile.objects.exists())
        self.assertFalse(get_user_model().objects.exists())
        self.assertEqual(Teacher.objects.get(slug='mohammed-atalla').name,'Mohammed Atalla')
    def test_existing_rows_update_once_preserving_unpublished_prices_and_booking_configuration(self):
        call_command('seed_catalog',verbosity=0)
        teacher=Teacher.objects.get(slug='amin-monemian');teacher.price=42;teacher.name='Old name';teacher.save()
        user=get_user_model().objects.create_user(username='existing-teacher')
        profile=TeachingProfile.objects.create(user=user,teacher=teacher,biography='Old bio',timezone='America/Vancouver',approved=True,meeting_provider='lms',meeting_url='https://lms.recitera.com/class/known')
        migration=importlib.import_module('catalog.migrations.0010_import_uploaded_teacher_profiles')
        migration.import_profiles(apps,connection.schema_editor())
        teacher.refresh_from_db();profile.refresh_from_db()
        self.assertEqual(teacher.name,'Amin Monemian');self.assertEqual(teacher.price,42)
        self.assertEqual(profile.biography,teacher.biography)
        self.assertEqual(profile.timezone,'America/Vancouver');self.assertTrue(profile.approved)
        self.assertEqual(profile.meeting_url,'https://lms.recitera.com/class/known')
        teacher.biography='Later administrator edit';teacher.save()
        call_command('seed_catalog',verbosity=0)
        teacher.refresh_from_db();self.assertEqual(teacher.biography,'Later administrator edit')

    def test_mohammed_followup_import_updates_only_his_public_profile(self):
        call_command('seed_catalog',verbosity=0)
        row=json.loads((Path(__file__).parent/'mohammed_profile_20261020.json').read_text())
        teacher=Teacher.objects.get(slug='mohammed-atalla')
        user=get_user_model().objects.create_user(username='mohammed-existing')
        profile=TeachingProfile.objects.create(user=user,teacher=teacher,biography='Old biography',timezone='Africa/Cairo',approved=True,meeting_url='https://meet.google.com/existing-room')
        untouched=list(Teacher.objects.exclude(pk=teacher.pk).values())
        teacher.name='Old name';teacher.biography='Old biography';teacher.save()
        importlib.import_module('catalog.migrations.0011_import_mohammed_profile').import_profile(apps,connection.schema_editor())
        teacher.refresh_from_db();profile.refresh_from_db()
        self.assertEqual(teacher.biography,row['biography']);self.assertEqual(teacher.based_in,'Egypt')
        self.assertEqual(teacher.name,'Mohammed Atalla');self.assertEqual(teacher.price,Decimal('30'))
        self.assertEqual(profile.biography,row['biography']);self.assertEqual(profile.timezone,'Africa/Cairo')
        self.assertTrue(profile.approved);self.assertEqual(profile.meeting_url,'https://meet.google.com/existing-room')
        self.assertEqual(list(Teacher.objects.exclude(pk=teacher.pk).values()),untouched)
        response=APIClient().get('/api/academy/teachers/mohammed-atalla/').json()
        for key in ['name','based_in','experience','languages','specialities','biography']:self.assertEqual(response[key],row[key])
        self.assertNotIn('meeting_url',response)
