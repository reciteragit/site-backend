import os
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Create a configured administrator once, preserving existing accounts"

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
        if not username or not password:
            self.stdout.write("Administrator provisioning not configured; existing accounts unchanged.")
            return
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write("Administrator account already exists; credentials unchanged.")
            return
        user = User(username=username, email=os.getenv("DJANGO_SUPERUSER_EMAIL", ""))
        validate_password(password, user=user)
        User.objects.create_superuser(username=username, email=user.email, password=password)
        self.stdout.write(self.style.SUCCESS("Configured administrator created."))
