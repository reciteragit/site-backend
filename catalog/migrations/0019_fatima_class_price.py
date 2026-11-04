from decimal import Decimal
from django.db import migrations


def update_price(apps,schema_editor):
    apps.get_model('catalog','Teacher').objects.using(schema_editor.connection.alias).filter(
        slug='fatima-abdulkazem',
    ).update(price=Decimal('30.00'))


class Migration(migrations.Migration):
    dependencies=[('catalog','0018_unpublish_two_teachers')]
    operations=[migrations.RunPython(update_price,migrations.RunPython.noop)]
