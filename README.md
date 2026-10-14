# Recitera Django REST backend

Django 5.2 LTS, Django REST Framework, PostgreSQL/Supabase, and authenticated Django admin. The frontend is `reciteragit/site` (Next.js).

## Local setup

Python 3.12 is validated.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
export DJANGO_DEBUG=true
# Optional locally: export DATABASE_URL=postgresql://...
# For local PostgreSQL without TLS only: export DATABASE_SSL_REQUIRED=false
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_catalog
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
```

Environment variables must be exported: Django does not auto-load `.env.example`. SQLite is supported only when `DJANGO_DEBUG=true` and no `DATABASE_URL` is set. Production requires PostgreSQL and a secret key; it fails closed without them. Do not set debug mode on Vercel.

Run the Next.js frontend with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api`; default local frontend origins on port 3000 are allowed only in debug mode. For a different port, set `CORS_ALLOWED_ORIGINS` to its exact origin.

## API and admin

- `GET /api/health/`: database and migrated catalog readiness; returns 503 if unavailable.
- `GET /api/teachers/` and `/api/teachers/<slug>/`: published teacher data.
- `GET /api/courses/` and `/api/courses/<slug>/`: published courses whose teacher is published.
- `/admin/`: manage teachers, languages, prices, order, publication, and course details.

Catalog responses are arrays. API writes are not enabled. Admin requires staff authentication and CSRF protection; there are no default production credentials. Password validators are enabled. Existing academy booking, payment, and application destinations remain external; this migration does not implement payment processing.

`seed_catalog` creates missing original entries and preserves later edits. Run migrations explicitly on the production database; the Vercel entry point never migrates or creates an admin during requests.

## Tests

```bash
DJANGO_DEBUG=true .venv/bin/python manage.py collectstatic --noinput
DJANGO_DEBUG=true .venv/bin/python manage.py test --verbosity 2
```

To test PostgreSQL, export its `DATABASE_URL` and retain SSL unless using an isolated local server without TLS. Django tests create a separate test database; the database user needs that permission. Do not run the test suite against a shared production database.

Tests exercise catalog import idempotence, publication, public read-only access, API details, readiness, admin access, and an admin edit reflected in the API. Production deployment readiness must be validated separately.

## Vercel + Supabase

Deploy this repository as a separate Vercel Python project using the root `vercel.json`. Python dependencies are pinned in `requirements.txt`; `api/index.py` exposes the Django WSGI `app`. WhiteNoise serves Django admin assets collected into ephemeral `/tmp` on cold starts. All persistent state uses PostgreSQL, including sessions.

Use the Supabase Free project **transaction pooler** URL with SSL. Keep `DATABASE_SSL_REQUIRED=true`. Configure `DJANGO_SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `CORS_ALLOWED_ORIGINS` in Vercel; see `.env.example` for names. Do not commit values.

Initialization from a trusted terminal:

```bash
python manage.py migrate --noinput
python manage.py seed_catalog
python manage.py createsuperuser
```

Then verify `/api/health/`, admin login, and frontend catalog fetching. For the complete ordered deployment steps, see `docs/deployment.md` in the frontend repository. Local validation does not prove Vercel or Supabase has been deployed.
