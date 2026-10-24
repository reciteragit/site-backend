import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

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
