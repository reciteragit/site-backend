from django.db import migrations


def enable_course_checkout(apps, schema_editor):
    from catalog.stripe_gateway import ready
    Settings = apps.get_model('catalog', 'StripeSettings')
    Course = apps.get_model('catalog', 'Course')
    alias = schema_editor.connection.alias
    config = Settings.objects.using(alias).first()
    content_ready = Course.objects.using(alias).filter(
        delivery_mode='platform', published=True, teacher__published=True,
        currency='CAD', episodes__published=True,
    ).exclude(episodes__video_url='').exists()
    if config and not config.courses_enabled and content_ready and ready(config):
        Settings.objects.using(alias).filter(pk=config.pk).update(courses_enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0016_shorten_teacher_display_names'),
        ('learning', '0004_publish_configured_surah_episodes'),
    ]
    operations = [migrations.RunPython(enable_course_checkout, migrations.RunPython.noop)]
