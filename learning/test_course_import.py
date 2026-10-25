import json
from importlib import import_module
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.apps import apps
from django.db import connection
from django.core.exceptions import ValidationError

from academy.tests import fixture
from catalog.models import Course
from learning.models import Episode


class RecordedCourseImportTests(TestCase):
    def setUp(self):
        _, _, teacher, _, _, _ = fixture()
        self.course = Course.objects.create(slug='import-surah', title='Import Surah', teacher=teacher.teacher,
                                            price=5, delivery_mode='external', course_url='https://academy.example.org/surah')

    def run_import(self, rows, apply=False):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.json'
            path.write_text(json.dumps(rows))
            call_command('import_recorded_courses', path, apply=apply, stdout=StringIO())

    def row(self, **changes):
        return dict(course_slug=self.course.slug, vimeo_video_id='123456',
                    video_url='https://vimeo.com/123456/abc123', **changes)

    def test_dry_run_then_idempotent_import_preserves_catalogue(self):
        self.run_import([self.row()])
        self.assertFalse(Episode.objects.exists())
        for _ in range(2):
            self.run_import([self.row()], apply=True)
        self.course.refresh_from_db()
        self.assertEqual(self.course.delivery_mode, 'platform')
        self.assertEqual(self.course.price, 5)
        self.assertEqual(self.course.course_url, 'https://academy.example.org/surah')
        self.assertEqual(Episode.objects.count(), 1)
        self.assertFalse(Episode.objects.get().is_free)

    def test_review_or_mismatched_link_cannot_activate_course(self):
        for url in ['', 'https://vimeo.com/reviews/review-token/videos/123456', 'https://vimeo.com/654321']:
            row = self.row()
            row['video_url'] = url
            with self.assertRaises(CommandError):
                self.run_import([row], apply=True)
        self.course.refresh_from_db()
        self.assertEqual(self.course.delivery_mode, 'external')
        self.assertFalse(Episode.objects.exists())

    def test_later_invalid_entry_causes_no_partial_import(self):
        with self.assertRaises(CommandError):
            self.run_import([self.row(), dict(course_slug='missing', video_url='')], apply=True)
        self.assertFalse(Episode.objects.exists())
        self.course.refresh_from_db()
        self.assertEqual(self.course.delivery_mode, 'external')

    def test_catalogue_conversion_creates_editable_draft_without_opening_checkout(self):
        from rest_framework.test import APIClient
        migration = import_module('learning.migrations.0003_internal_surah_courses')
        self.course.slug = migration.SLUGS[0]
        self.course.save()
        with connection.schema_editor(atomic=False) as editor:
            migration.convert_courses(apps, editor)
            migration.convert_courses(apps, editor)
        self.course.refresh_from_db()
        self.assertEqual(self.course.delivery_mode, 'platform')
        self.assertEqual(self.course.course_url, '')
        self.assertEqual(self.course.price, 5)
        episode = Episode.objects.get(course=self.course)
        self.assertEqual(episode.video_url, '')
        self.assertFalse(episode.published)
        episode.full_clean()
        episode.published = True
        with self.assertRaises(ValidationError):
            episode.full_clean()
        response = APIClient().get(f'/api/academy/learning/courses/{self.course.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['ready'])
        self.assertEqual(response.data['episodes'], [])

    def test_configured_placeholders_publish_but_blank_and_unrelated_drafts_stay_hidden(self):
        from rest_framework.test import APIClient
        migration = import_module('learning.migrations.0004_publish_configured_surah_episodes')
        slugs = import_module('learning.migrations.0003_internal_surah_courses').SLUGS
        self.course.slug = slugs[0]
        self.course.delivery_mode = 'platform'
        self.course.save()
        valid = Episode.objects.create(course=self.course, title='Ready', video_url='https://vimeo.com/123456/abc123', published=False)
        blank = Episode.objects.create(course=self.course, title='Not ready', video_url='', published=False)
        invalid = Episode.objects.create(course=self.course, title='Review link', video_url='https://vimeo.com/reviews/token/videos/123456', published=False)
        other = Course.objects.create(slug='unrelated-draft',title='Other',teacher=self.course.teacher,price=5,delivery_mode='platform')
        draft = Episode.objects.create(course=other,title='Intentional draft',video_url='https://vimeo.com/123456',published=False)
        with connection.schema_editor(atomic=False) as editor:
            migration.publish_configured_episodes(apps, editor)
            migration.publish_configured_episodes(apps, editor)
        for episode, expected in [(valid,True),(blank,False),(invalid,False),(draft,False)]:
            episode.refresh_from_db()
            self.assertEqual(episode.published, expected)
        response = APIClient().get(f'/api/academy/learning/courses/{self.course.slug}/')
        self.assertTrue(response.data['ready'])
        self.assertEqual(response.data['episode_count'], 1)
        self.assertFalse(response.data['episodes'][0]['accessible'])
        from learning.services import purchase_courses
        self.assertEqual(purchase_courses('course',self.course.slug), [self.course])
