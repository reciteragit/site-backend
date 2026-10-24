from django.db import migrations


NAMES = [
    ('selsebil-benelhaj-sghaier', 'Selsebil Benelhaj Sghaier', 'Selsebil Benelhaj'),
    ('amir-hossein-rezaaee', 'Amir Hossein Rezaaee', 'Amir Hossein'),
    ('setayesh-zahra-rezaaee', 'Setayesh Zahra Rezaaee', 'Setayesh Zahra'),
    ('ahmed-ayman-elshazly', 'Ahmed Ayman Elshazly', 'Ahmed Ayman'),
]


def shorten_names(apps, schema_editor):
    Teacher = apps.get_model('catalog', 'Teacher')
    for slug, previous, current in NAMES:
        Teacher.objects.using(schema_editor.connection.alias).filter(
            slug=slug, name=previous,
        ).update(name=current)


class Migration(migrations.Migration):
    dependencies = [('catalog', '0015_discountcode_bundles_paymentorder_buyer_and_more')]
    operations = [migrations.RunPython(shorten_names, migrations.RunPython.noop)]
