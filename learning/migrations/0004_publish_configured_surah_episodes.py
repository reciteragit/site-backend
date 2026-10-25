from django.core.exceptions import ValidationError
from django.db import migrations


def publish_configured_episodes(apps, schema_editor):
    # Only activate the twelve placeholder curricula requested by the owner.
    # Leave blank/invalid links and unrelated, deliberately drafted courses alone.
    from learning.models import validate_video_url, vimeo_embed
    from importlib import import_module
    slugs = import_module('learning.migrations.0003_internal_surah_courses').SLUGS
    Episode = apps.get_model('learning', 'Episode')
    alias = schema_editor.connection.alias
    rows = Episode.objects.using(alias).filter(
        course__slug__in=slugs, course__delivery_mode='platform', published=False,
    ).exclude(video_url='')
    for episode in rows.iterator():
        try:
            validate_video_url(episode.video_url)
            if episode.video_provider == 'vimeo':
                vimeo_embed(episode.video_url)
            elif episode.video_provider != 'direct':
                continue
        except ValidationError:
            continue
        Episode.objects.using(alias).filter(pk=episode.pk).update(published=True)


class Migration(migrations.Migration):
    dependencies = [('learning', '0003_internal_surah_courses')]
    operations = [migrations.RunPython(publish_configured_episodes, migrations.RunPython.noop)]
