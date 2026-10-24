import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Course
from learning.models import Episode, vimeo_embed


class Command(BaseCommand):
    help = 'Validate a course/video manifest; use --apply to import verified playback URLs.'

    def add_arguments(self, parser):
        parser.add_argument('manifest', type=Path)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            rows = json.loads(options['manifest'].read_text())
        except (OSError, ValueError) as exc:
            raise CommandError('Cannot read the JSON course manifest.') from exc
        if not isinstance(rows, list) or not rows:
            raise CommandError('The manifest must contain a nonempty list of courses.')
        pending, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise CommandError('Each manifest entry must be an object.')
            slug = row.get('course_slug')
            if not isinstance(slug, str) or not slug or slug in seen:
                raise CommandError('Each course slug must be nonempty and unique.')
            seen.add(slug)
            try:
                course = Course.objects.select_for_update().get(slug=slug)
            except Course.DoesNotExist:
                raise CommandError(f'Course not found: {slug}') from None
            video_url = row.get('video_url', '')
            if not video_url:
                raise CommandError(f'{slug}: add the verified Vimeo Share/Embed URL; a Review link is not a playback URL.')
            try:
                embed = vimeo_embed(video_url)
                expected = str(row.get('vimeo_video_id', ''))
                if not expected or embed.split('/video/', 1)[1].split('?', 1)[0] != expected:
                    raise ValidationError('The playback URL does not match the supplied video ID.')
                existing = list(course.episodes.select_for_update().all())
                if len(existing) > 1:
                    raise CommandError(f'{slug}: multiple episodes exist; manage them in admin to avoid replacing a curriculum.')
                episode = existing[0] if existing else Episode(course=course)
                if existing and episode.video_url and vimeo_embed(episode.video_url) != embed:
                    raise CommandError(f'{slug}: a different video already exists; review it in admin.')
                episode.title = course.title
                episode.video_provider = 'vimeo'
                episode.video_url = video_url
                episode.sort_order = 0
                episode.published = True
                episode.is_free = course.price == 0
                episode.full_clean()
            except ValidationError as exc:
                raise CommandError(f'{slug}: {"; ".join(exc.messages)}') from exc
            pending.append((course, episode))
        if not options['apply']:
            self.stdout.write(f'Validated {len(pending)} courses. No changes; rerun with --apply after checking Vimeo playback on the site domain.')
            return
        for course, episode in pending:
            episode.save()
            course.delivery_mode = 'platform'
            course.save(update_fields=['delivery_mode'])
        self.stdout.write(self.style.SUCCESS(f'Imported {len(pending)} course videos; existing prices, teachers and publication settings preserved.'))
