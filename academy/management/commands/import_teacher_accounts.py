"""One-time, atomic teacher account provisioning from a private environment payload."""
import hashlib
import json
import os
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from academy.models import AccessToken, Profile, TeachingProfile
from catalog.models import Teacher


class Command(BaseCommand):
    help = 'Import teacher logins from TEACHER_ACCOUNTS_IMPORT_JSON; never logs credentials.'

    def handle(self, *args, **options):
        raw = os.getenv('TEACHER_ACCOUNTS_IMPORT_JSON', '')
        if not raw:
            return
        try:
            payload = json.loads(raw)
            batch = payload['batch']
            password = payload['initial_password']
            rows = payload['teachers']
            if not isinstance(batch, str) or not batch or not isinstance(password, str) or len(password) < 8 or not isinstance(rows, list) or not rows:
                raise ValueError()
            emails, slugs = set(), set()
            for row in rows:
                row['email'] = row['email'].strip().lower()
                validate_email(row['email'])
                if row['email'] in emails or row['slug'] in slugs:
                    raise ValueError()
                emails.add(row['email']); slugs.add(row['slug'])
        except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
            raise CommandError('Invalid teacher account import payload; no changes applied.') from None
        marker = 'teacher-import-' + hashlib.sha256(batch.encode()).hexdigest()
        User = get_user_model()
        with transaction.atomic():
            group, _ = Group.objects.get_or_create(name=marker)
            Group.objects.select_for_update().get(pk=group.pk)
            changed = 0
            for row in sorted(rows, key=lambda r: r['slug']):
                teacher = Teacher.objects.select_for_update().filter(slug=row['slug']).first()
                users = list(User.objects.select_for_update().filter(email__iexact=row['email']))
                if teacher is None or len(users) > 1:
                    raise CommandError('Missing teacher or ambiguous account; entire import rolled back.')
                user = users[0] if users else User(username=row['email'], email=row['email'], first_name=row.get('first_name', ''), last_name=row.get('last_name', ''))
                if user.pk and user.groups.filter(pk=group.pk).exists():
                    continue
                linked = TeachingProfile.objects.select_for_update().filter(teacher=teacher).first()
                own = TeachingProfile.objects.select_for_update().filter(user=user).first() if user.pk else None
                if (linked and linked.user_id != user.pk) or (own and own.teacher_id != teacher.pk) or user.is_staff or user.is_superuser or not user.is_active:
                    raise CommandError('Account ownership conflict or protected account; entire import rolled back.')
                user.set_password(password)
                user.save()
                Profile.objects.get_or_create(user=user)
                profile, _ = TeachingProfile.objects.get_or_create(user=user, defaults={'teacher': teacher, 'biography': teacher.biography, 'approved': True})
                if not profile.approved:
                    profile.approved = True
                    profile.save(update_fields=['approved'])
                AccessToken.objects.filter(user=user).delete()
                user.groups.add(group)
                changed += 1
        self.stdout.write(f'Teacher account import complete: {changed} provisioned; completed batch entries preserved.')
