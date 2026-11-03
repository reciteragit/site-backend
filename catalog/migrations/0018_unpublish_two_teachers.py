from django.db import migrations


def unpublish(apps,schema_editor):
    apps.get_model('catalog','Teacher').objects.using(schema_editor.connection.alias).filter(
        slug__in=['amir-hossein-rezaaee','setayesh-zahra-rezaaee'],
    ).update(published=False)


class Migration(migrations.Migration):
    dependencies=[('catalog','0017_enable_ready_course_checkout')]
    operations=[migrations.RunPython(unpublish,migrations.RunPython.noop)]
