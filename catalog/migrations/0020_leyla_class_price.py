from decimal import Decimal
from django.db import migrations


def update_price(apps, schema_editor):
    apps.get_model('catalog', 'Teacher').objects.using(schema_editor.connection.alias).filter(
        slug='leyla-hosseini',
    ).update(price=Decimal('30.00'))


class Migration(migrations.Migration):
    dependencies = [('catalog', '0019_fatima_class_price')]
    operations = [migrations.RunPython(update_price, migrations.RunPython.noop)]
