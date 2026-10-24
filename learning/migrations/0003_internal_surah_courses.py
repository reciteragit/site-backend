from django.db import migrations


SLUGS = [
    'surah-al-ikhlas-step-by-step', 'surah-quraysh-step-by-step',
    'surah-al-asr-step-by-step', 'surah-al-falaq-step-by-step',
    'surah-al-fil-step-by-step', 'surah-al-humazah-step-by-step',
    'surah-al-kafirun-step-by-step', 'surah-al-kawthar-step-by-step',
    'surah-al-maun-step-by-step', 'surah-al-masad-step-by-step',
    'surah-an-nas-step-by-step', 'surah-an-nasr-step-by-step',
]


def convert_courses(apps, schema_editor):
    Course = apps.get_model('catalog', 'Course')
    Episode = apps.get_model('learning', 'Episode')
    alias = schema_editor.connection.alias
    for course in Course.objects.using(alias).filter(slug__in=SLUGS):
        course.delivery_mode = 'platform'
        course.course_url = ''
        course.save(using=alias, update_fields=['delivery_mode', 'course_url'])
        if not Episode.objects.using(alias).filter(course_id=course.pk).exists():
            Episode.objects.using(alias).create(
                course_id=course.pk, title=course.title, video_url='',
                published=False, is_free=course.price == 0,
            )


class Migration(migrations.Migration):
    dependencies = [
        ('learning', '0002_draft_episode_video'),
        ('catalog', '0015_discountcode_bundles_paymentorder_buyer_and_more'),
    ]
    operations = [migrations.RunPython(convert_courses, migrations.RunPython.noop)]
