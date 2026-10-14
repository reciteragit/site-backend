import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from catalog.models import Teacher, Course

class Command(BaseCommand):
    help = "Import the original website catalog without overwriting admin edits"

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads((Path(__file__).resolve().parents[2] / "seed.json").read_text())
        created = 0
        for row in data["teachers"]:
            row = row.copy()
            slug = row.pop("slug")
            _, added = Teacher.objects.get_or_create(slug=slug, defaults=row)
            created += added
        for row in data["courses"]:
            row = row.copy()
            slug = row.pop("slug")
            teacher = Teacher.objects.get(slug=row.pop("teacher_slug"))
            _, added = Course.objects.get_or_create(slug=slug, defaults={**row, "teacher": teacher})
            created += added
        self.stdout.write(self.style.SUCCESS(f"Created {created} catalog entries; existing admin edits preserved."))
