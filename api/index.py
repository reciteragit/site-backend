"""Vercel Python WSGI entry point; migrations run separately, never on requests."""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_STATIC_ROOT", "/tmp/recitera-static")
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
if not (settings.STATIC_ROOT / "admin/css/base.css").exists():
    call_command("collectstatic", interactive=False, verbosity=0)
from django.core.wsgi import get_wsgi_application
app = get_wsgi_application()
application = app
