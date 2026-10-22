# Recitera admin redesign

## Open-source theme review (22 October 2026)

| Theme | License | Fit for this project |
| --- | --- | --- |
| [Django Unfold](https://github.com/unfoldadmin/django-unfold) | MIT | Selected: Django 5.2 / Python 3.12 support, responsive navigation, accessible form widgets, command search and light/dark themes. |
| [Django Jazzmin](https://github.com/farridav/django-jazzmin) | MIT | Established Bootstrap/AdminLTE option; a more traditional interface. |
| [Django Admin Interface](https://github.com/fabiocaccamo/django-admin-interface) | MIT | Good for changing the classic admin's colors and branding; less suited to a custom operational overview. |

The implementation uses the free `django-unfold==0.110.0` package, not a paid dashboard kit. Its upstream license remains distributed with the dependency. Fonts, icons, CSS and JavaScript are served from the backend's own static files; no external font service or UI CDN is required.

## What changed

- Recitera forest-green navigation, warm neutral surfaces, readable status badges, keyboard focus indicators, responsive layout and dark mode.
- Navigation grouped into Academy, People & applications, Payments and Administration. Each entry follows the registered ModelAdmin's permissions, including the superuser-only Stripe settings.
- Real, permission-filtered overview: live paid revenue for the last 7/30/90 days, confirmed classes in the next seven days, published teachers and unreviewed applications. Different currencies are shown separately; test and unpaid orders are excluded from revenue.
- Upcoming classes, a seven-day confirmed-class activity chart, unsent confirmations, payment-review queue, teacher approvals and scholarship requests. Links use native Django admin filters.
- Calendar dates use the administrator's existing profile timezone, falling back to UTC, and label the timezone explicitly. Datetimes remain stored in UTC.
- Teacher, course, classroom and application forms grouped into clear sections. Existing attachment download permissions, write-only Stripe secrets and booking/payment restrictions remain in place.
- Django authentication, model permissions, CSRF protection, autocomplete, inline attachments, history, list editing and existing email actions are retained. The overview only reads data.
- Direct admin login redirects to `/admin/`; a safe `next` destination is retained when opening a deep link.

## Files and maintenance

- `config/admin_ui.py`: theme, navigation and branding.
- `config/dashboard.py`: overview queries and permission checks.
- `templates/admin/index.html`: overview template.
- `templates/admin/login.html`: login return destination and branding.
- `static/recitera/admin.css`: brand styles and responsive/dark variants.
- `academy/admin.py`, `catalog/admin.py`, `catalog/payment_admin.py`: native admin enhancements.

No database migration or production demo data is required. Public frontend and payment/booking APIs are unchanged.

Before testing or deploying after a dependency/static-file change:

```sh
DJANGO_DEBUG=true .venv/bin/python manage.py collectstatic --noinput
```

Run the backend suite against PostgreSQL. `academy.test_admin_dashboard` additionally checks restricted staff, live revenue by currency, every registered admin list/add screen, important detail forms, filter links and login redirects. Browser review covers desktop/mobile, theme switching and form interactions in an isolated local preview database.
