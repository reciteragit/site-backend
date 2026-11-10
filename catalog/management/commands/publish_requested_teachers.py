"""Publish the five explicitly requested applicants using saved form data only."""
import re
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from catalog.models import Teacher, TeacherApplication

REQUESTED = [
    ('Muhammad Shafi', 'muhammad-shafi'),
    ('Asma Allah Dad', 'asma-allah-dad'),
    ('Marium Abdul haseeb', 'marium-abdul-haseeb'),
    ('Rayyan Yousaf', 'rayyan-yousaf'),
    ('Adan Madker', 'adan-madker'),
]


def normalize(value):
    return re.sub(r'\s+', ' ', value.strip()).casefold()


class Command(BaseCommand):
    help = 'Publish requested teachers from existing application forms, at 30 CAD without photos.'

    @transaction.atomic
    def handle(self, *args, **options):
        requested = {normalize(name): (name, slug) for name, slug in REQUESTED}
        matches = {}
        # Newest submission wins; applicant may have updated their form.
        for application in TeacherApplication.objects.order_by('-pk').iterator():
            names = [application.full_name, f'{application.first_name} {application.last_name}']
            for value in names:
                key = normalize(value)
                if key in requested and key not in matches:
                    matches[key] = application
        created = 0
        for key, (name, slug) in requested.items():
            if Teacher.objects.filter(slug=slug).exists():
                continue  # Preserve future administrator edits.
            application = matches.get(key)
            if application is None:
                self.stdout.write(self.style.WARNING(f'No saved application matched {name}; profile not created.'))
                continue
            languages = [value for value in application.languages if value != 'Other']
            if 'Other' in application.languages and application.other_languages.strip():
                languages += [value.strip() for value in application.other_languages.split(',') if value.strip()]
            experience = f'{application.years_of_experience} years' if application.years_of_experience is not None else ''
            bio = [f'{name} is a Quran teacher' + (f' based in {application.country}.' if application.country else '.')]
            if experience: bio.append(f'Teaching experience: {experience}.')
            if application.specializations: bio.append('Specialties: ' + ', '.join(application.specializations) + '.')
            if languages: bio.append('Teaching languages: ' + ', '.join(languages) + '.')
            if application.timezone: bio.append('Teaching time zone: ' + application.timezone + '.')
            Teacher.objects.create(
                slug=slug, name=name, based_in=application.country, experience=experience,
                languages=languages, specialities=application.specializations, biography='\n'.join(bio),
                image='/assets/teacher-placeholder.svg', profile_url=f'https://www.recitera.com/teachers/{slug}',
                price=Decimal('30.00'), currency='CAD', published=True,
                sort_order=(Teacher.objects.aggregate(value=Max('sort_order'))['value'] or 0) + 1,
            )
            created += 1
        self.stdout.write(f'Created {created} requested teacher profiles from saved forms.')
