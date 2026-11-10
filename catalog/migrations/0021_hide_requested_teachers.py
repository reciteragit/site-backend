from django.db import migrations


def unpublish(apps, schema_editor):
    apps.get_model('catalog', 'Teacher').objects.using(schema_editor.connection.alias).filter(
        slug__in=['muhammad-shafi', 'asma-allah-dad', 'marium-abdul-haseeb', 'rayyan-yousaf', 'adan-madker'],
    ).update(published=False)


class Migration(migrations.Migration):
    dependencies = [('catalog', '0020_leyla_class_price')]
    operations = [migrations.RunPython(unpublish, migrations.RunPython.noop)]
