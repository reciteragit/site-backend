# Native class booking

Next.js frontend: `/sign-in`, `/account`, `/account/teaching`, `/teachers/<slug>`,
`/cart`, `/checkout`. Django API: `/api/academy/`. The existing donation and course
catalogue remain in place. Recorded-course content/fulfilment still lives on the
existing academy; this change implements native one-to-one class booking.

## Teacher onboarding and classrooms

1. The teacher registers a new account and opens Teacher dashboard. These are
   native Django accounts; external academy accounts/passwords are not imported.
2. Save a teacher profile, an IANA region such as `America/Toronto`, and a CAD
   price per class. Add explicit dated available class slots (15–180 minutes).
   Availability may be entered before approval, but is not public until approved.
3. In Django admin → Academy → Teaching profiles, select the user and catalogue
   teacher. Existing catalogue teachers can be attached to a newly registered
   account by an administrator; do not create duplicate published profiles.
4. An administrator sets the classroom provider and private HTTPS meeting URL:
   Zoom (`zoom.us` / `zoom.com` and their subdomains), Google Meet
   (`meet.google.com`), or Recitera LMS (`lms.recitera.com`). New teaching profiles
   default to `https://lms.recitera.com/`; migration 0003 applies that destination
   to existing profiles once. Administrators can subsequently override it.
   Zoom and Google Meet URLs must contain
   a class/room path. This configures links; it does not provision Zoom/Meet
   meetings or implement/host the separate Recitera LMS conferencing service.
5. Approve the teaching profile **and publish its catalogue teacher**. Students
   may now see available dates and add classes to their cart.
6. Booking URLs are snapshotted at checkout. An administrator can override a
   specific confirmed Booking's `meeting_url`; this requeues its notifications.
   Updating the teacher's default URL affects future checkouts only.

Teacher users cannot approve themselves, publish catalogue status, change their
classroom link, or change another teacher's availability. Only owned student
bookings or a teacher's own confirmed bookings expose classroom URLs/student info.

## Time zones and booking integrity

Times are stored as aware UTC instants. Teachers enter **local wall time plus
saved IANA zone**; users initially see their browser's
`Intl.DateTimeFormat().resolvedOptions().timeZone`, with an explicit selector.
DST gaps and repeated/ambiguous local times are rejected rather than guessed.
Changing a time zone does not move existing slots. A booking snapshots the user's
selected notification zone and the teacher's zone. Confirmation emails show each
recipient's time; ICS files contain UTC instants for calendar conversion.

Slots are individual dated classes, not automatic recurring rules. Teachers can
add/remove unreserved future slots. A cart is not a reservation. Checkout locks
teacher records in stable order and holds all selected slots atomically.
PostgreSQL conditional uniqueness enforces one held/confirmed booking per slot.
Students cannot reserve overlapping classes, and teachers cannot publish
intersecting slots. The checkout price is calculated on the server and frozen in
the booking; the browser cannot override it.

Stripe card-only checkout expires after about 31 minutes. Database holds last
36 minutes to allow webhook delivery. Unpaid/expired/failed holds are released
lazily on schedule reads and by the daily cron. Cancel-return alone never releases
a still-payable session. An interrupted Stripe call retains the hold: retries use
the same request/session idempotency key. A paid return URL never confirms a class.
Only signed, amount/currency/mode/session-matched Stripe webhooks do. Late payment
that conflicts with a new reservation goes to `payment_review` for administrator
resolution/refund; it must not send a false confirmation or double-book a slot.
Refund/cancellation/rescheduling policies and automatic refunds are not introduced.

## Payment setup

Keep the existing Stripe settings/webhook integration. Set
`ACADEMY_PAYMENTS_ENABLED=true` to opt into class checkout during the build's
`manage.py configure_academy`. This requires a ready, signed Stripe connection and
sets `StripeSettings.lessons_enabled`. Existing live/test credentials and other
payment toggles are preserved. The account currently uses Stripe test mode;
UI/email label sandbox bookings and no real payment is implied.

Old anonymous `purpose=lesson` payments are rejected: class purchases must use
this authenticated cart flow with explicit time slots. Donations are unchanged.

## Email setup and retries

Recommended on Vercel: install the Resend integration from
https://vercel.com/marketplace/resend and connect it to `site-backend`.
The integration injects `RESEND_API_KEY`; Django automatically selects
`academy.email_backend.ResendBackend` when this key exists, unless EMAIL_BACKEND
is explicitly overridden. The backend calls Resend over verified HTTPS, attaches
base64 ICS data and uses a stable per-content idempotency key for retries.
The existing durable outbox/retry paths are unchanged. Sender acceptance is tracked
as sent; actual inbox delivery/bounce tracking requires the provider dashboard.

Verify `recitera.com` in Resend Domains by adding its exact DNS records in your DNS
provider. Keep `DEFAULT_FROM_EMAIL=info@recitera.com`. Do not use Resend's onboarding
sender for customer email, impersonate an unverified domain or replace existing MX
records for the root domain. A Gmail address can be used to sign into Resend; this
does not change the verified sender or create an inbox at info@recitera.com.
Resend sends transactional email; receiving messages at that address requires a
separate mailbox/forwarding service.

Alternative: production can also use SMTP. Configure:

- `DEFAULT_FROM_EMAIL=info@recitera.com`
- `EMAIL_HOST`, `EMAIL_PORT` (usually 587), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS=true`, `EMAIL_USE_SSL=false` (or the provider's appropriate pair)
- `CRON_SECRET` (a generated random secret; Vercel sends it as Bearer auth)

Verify the sender/domain and SPF/DKIM with the provider. Never commit credentials.
Use a transactional-capable provider that accepts SMTP from Vercel. Real inbox
arrival needs the actual provider; local-memory mail success proves message
composition/queueing only.

If neither RESEND_API_KEY nor SMTP is configured, confirmations remain queued.
No real send is claimed until the provider accepts the verified sender.

Each confirmed class creates separate durable email deliveries for student and
teacher, including time, private link and ICS attachment. Webhooks attempt immediate
delivery within a bounded time budget. A database lease prevents parallel workers
from claiming the same message. Failed/missing-service deliveries remain queued;
bookings stay confirmed and the class link remains visible in the account.
Django admin → Email deliveries → Retry selected unsent confirmations, the
learner's Retry confirmation email button, or `python manage.py send_booking_emails`
can retry. A free-tier-compatible daily Vercel cron at 08:00 UTC retries the outbox;
for lower retry latency configure a suitable external scheduler/plan. SMTP cannot
guarantee exactly-once delivery after a process crash; stable Message-ID helps
providers identify retries. No fake successful delivery or memory-only background
threads are used in production.

## Authentication and verification

The BFF proxies a fixed allowlist of API paths, verifies Origin for JSON writes,
and keeps opaque bearer tokens in HttpOnly/Secure/SameSite cookies. Tokens are
stored as SHA-256 digests with 14-day expiration; passwords use Django hashing and
password validation. Password change revokes all sessions. Accounts and teachers
have ownership checks. Production should use a shared Django cache for consistent
DRF throttling across serverless instances. The browser never receives API tokens.

Run using local databases only:

```
DJANGO_DEBUG=true DATABASE_URL= POSTGRES_URL= .venv/bin/python manage.py test
```

The concurrency test is skipped on SQLite and must also pass against PostgreSQL.
Set a disposable PostgreSQL `DATABASE_URL` with `DJANGO_DEBUG=true` and run the same
suite. Do not run tests against production. Frontend: `npm run typecheck` and
`npm run build`. Test an owned local browser flow, including signed fixture webhook,
private calendar download, unavailable-slot removal, different IANA zones and
teacher/student ownership. No real payment, external meeting or production email
is required or claimed by those fixture tests.

Operator-only domain verification: `python manage.py check_email_domain --verify`
checks the Resend domain without printing credentials and never sends a test by
default. A sending-only API key may not allow domain metadata reads; a successful
provider-accepted send still demonstrates the configured sender is permitted.
Pass `--test-recipient` only after the recipient authorizes a test, and only for a
one-off operation. An operator may alternatively set temporary
RECITERA_EMAIL_TEST_RECIPIENT for an explicitly authorized one-off deployment;
remove that variable immediately afterwards. RESEND_DOMAIN_ID allows direct
domain-status reads. Never put a literal test recipient in the permanent build
command or cron. Without the flag/temporary variable, domain checks do not send.

## Imported public teacher profiles (20 October 2026)

The user supplied six saved public academy HTML pages. Their curated public data
is retained in `catalog/teacher_profiles_20261020.json` with source filename, URL
and SHA-256; raw HTML/scripts/login overlays are never embedded or executed.
`catalog` migration 0010 updates existing matched slugs once; fresh installations
use the updated seed. Keep the dated snapshot immutable because the migration
references it. Later admin edits survive normal seed_catalog builds.

Imported fields: full public name, country, teaching specialities and About me.
Only published single-session prices update: Fatima 20 CAD, Selsebil 30 CAD and
Amir Hossein 30 CAD. Pages with no course results do not provide a new rate, so
Amin, Abozar and Setayesh keep their existing prices. Country is not interpreted as
an IANA time zone. Existing user links, approval, classroom URLs, reservations,
paid order amounts and schedules are preserved. No account or available class is
invented. Mohammed Atalla had no corresponding uploaded page and is unchanged.

Public biography lives on catalogue Teacher so it displays before a teacher
account is linked. A linked TeachingProfile biography may override it; the one-off
import updates both for the six provided profiles. Admin/teacher editing remains
available. Saved HTML embedded-video subdocuments were not supplied, so no new
video URL or booking package implementation is inferred from their filenames.


Follow-up: the user subsequently supplied Mohammed atalla.html. The immutable
`catalog/mohammed_profile_20261020.json` snapshot and migration 0011 add Mohammed
Atalla's original About me, Egypt, Arabic, 4+ years, teaching specialities and
30 CAD single-class rate. The earlier six-profile snapshot/migration remain
unchanged. Existing private scheduling configuration and all other teachers are
preserved. Egypt is not used to guess or change the teacher's saved time zone.

Google login and explicit account linking are documented in
[GOOGLE_SIGN_IN.md](GOOGLE_SIGN_IN.md). Existing email/password users must sign in
before connecting Google; same-email Google claims do not silently merge accounts.

## Weekly availability

Teacher dashboard now saves a finite weekly plan (`teacher/availability`): IANA
zone, inclusive start/end dates, 15–180 minute classes and up to six time ranges
per weekday (Monday=0). The date range must be within the next 180 days; a plan
may generate at most 3,000 full classes. A short remainder is not bookable.
Each occurrence is converted independently from local wall time to UTC, so a
weekly 19:30 class stays at 19:30 after DST. Missing/ambiguous times and classes
crossing a clock change are skipped and reported.

Saving holds the same teacher row lock as checkout and manual slot creation.
It replaces only unreserved generated slots, retains unchanged slot IDs, and
preserves manual slots, held/confirmed bookings and their notification snapshots.
Conflicts with preserved slots are skipped and counted. An empty weekly plan
removes its unreserved generated availability. Plans end on their chosen end date;
teachers extend the range and save again to publish more weeks.

Students fetch `teachers/<slug>/availability?timezone=<IANA>` for available local
dates, then `teachers/<slug>/slots?date=YYYY-MM-DD&timezone=<IANA>` for that day's
compact slots. These endpoints expose neither classroom links nor identities.
The legacy slots query without a date remains supported.
