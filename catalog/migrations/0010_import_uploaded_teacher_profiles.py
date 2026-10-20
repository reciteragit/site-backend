import json
from pathlib import Path
from django.db import migrations


def import_profiles(apps,schema_editor):
    Teacher=apps.get_model('catalog','Teacher')
    TeachingProfile=apps.get_model('academy','TeachingProfile')
    database=schema_editor.connection.alias
    # Dated source snapshot is retained unchanged so historical migrations remain reproducible.
    rows=json.loads((Path(__file__).resolve().parents[1]/'teacher_profiles_20261020.json').read_text())
    # Match the profile-before-catalogue lock order used by teacher profile edits.
    list(TeachingProfile.objects.using(database).filter(teacher__slug__in=[row['slug'] for row in rows]).select_for_update(of=('self',)).order_by('pk'))
    for row in rows:
        values={key:row[key] for key in ['name','biography','based_in','specialities','price'] if key in row}
        Teacher.objects.using(database).filter(slug=row['slug']).update(**values)
        TeachingProfile.objects.using(database).filter(teacher__slug=row['slug']).update(biography=row['biography'])


class Migration(migrations.Migration):
    dependencies=[('catalog','0009_teacher_public_profile_details'),('academy','0001_initial')]
    operations=[migrations.RunPython(import_profiles,migrations.RunPython.noop)]
