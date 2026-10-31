#!/bin/sh
set -eu

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed_catalog
python manage.py sync_crm
python manage.py bootstrap_admin
python manage.py configure_stripe
python manage.py configure_academy
python manage.py check_email_domain --verify
