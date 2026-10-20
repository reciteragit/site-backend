import json
from pathlib import Path
from django.db import migrations


def import_profile(apps,schema_editor):
    Teacher=apps.get_model('catalog','Teacher')
    TeachingProfile=apps.get_model('academy','TeachingProfile')
    database=schema_editor.connection.alias
    row=json.loads((Path(__file__).resolve().parents[1]/'mohammed_profile_20261020.json').read_text())
    list(TeachingProfile.objects.using(database).filter(teacher__slug=row['slug']).select_for_update(of=('self',)).order_by('pk'))
    values={key:row[key] for key in ['name','based_in','experience','languages','specialities','biography','price','currency']}
    Teacher.objects.using(database).filter(slug=row['slug']).update(**values)
    TeachingProfile.objects.using(database).filter(teacher__slug=row['slug']).update(biography=row['biography'])


class Migration(migrations.Migration):
    dependencies=[('catalog','0010_import_uploaded_teacher_profiles')]
    operations=[migrations.RunPython(import_profile,migrations.RunPython.noop)]
