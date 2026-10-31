# CRM rollout: phase 1 (priorities 1 and 5)

This release implements the requested first phase: automatic lead capture and trial communication automation. It is not a claim that all six roadmap priorities have been completed.

## Operator paths

- Public trial enquiry: `/request-trial`, also linked from `/teachers`.
- Django admin → **CRM & onboarding → Lead pipeline** (`/admin/crm/lead/`).
- **Trial enquiries**: original read-only submissions and campaign tags.
- **Trial outcomes & feedback**: teacher attendance/assessment, learner feedback and next-step preference.
- **Communication queue**: due/sent/suppressed timestamps, attempts, sanitized errors and retry for failed unsent email.

Leads have New, Awaiting assessment, Trial booked, Trial completed, Converted and Dropped stages, assigned owner, preferred teacher, follow-up date, contact timezone/language, goals, qualitative staff notes and an immutable event history. Dropped leads require a reason. Converted/dropped leads are not regressed by repeated payment or booking events. If a booked trial is cancelled and no other upcoming trial exists, its lead returns to assessment.

## Capture, ownership and linking

New scholarship submissions, trial enquiries and confirmed live/free trial bookings are captured through transactional signals. Duplicate network retries and webhook events do not create duplicate leads, events or communication tasks. Test bookings do not create CRM trial leads. `python manage.py sync_crm` and the scheduled worker backfill existing missing records; old trials receive suppressed follow-up tasks rather than a historical email blast.

The lead represents the payer/contact account for this phase, not a separate child learner. Unauthenticated enquiry and scholarship forms are not assigned to a user just because an email matches. The trial acknowledgement contains a timestamped, signed, seven-day account-linking URL. A signed-in user must use the same email address and explicitly connect the enquiry. This merges its contact metadata, campaign, history and queued messages into the authenticated contact, preserving original source records. Link generation is deterministic per enquiry, so delivery retries reuse the same payload/provider idempotency key. Staff can review original sources. Family/child profiling is a later phase.

Real paid live classes and recorded courses/packages advance an existing verified contact to Converted. Test payments, donations, held orders and free checkouts do not masquerade as paid conversion. The worker reconciles payments/trials that committed concurrently. Support can still set lifecycle stages manually with an audited actor; the paid-conversion metric uses actual qualifying payment records, not a manual stage label.

## Communication automation

Email is the only automated channel, per the user's selection. The existing verified sender/Resend backend is reused. WhatsApp links in lead records open a manual contact action; there is no WhatsApp Web automation, SMS delivery or unauthorised channel account login.

- Trial enquiry: queued acknowledgement and account-connection link.
- Trial booking: existing confirmation/24-hour/30-minute emails retain the private class link for teacher and student.
- Trial reminder: additional email to both people five minutes before the trial. A late 30-minute reminder expires at the five-minute threshold for trials to avoid duplicate reminders then.
- Post-trial: one follow-up to the contact one hour after the scheduled end, asking how it went, requesting feedback and linking actual teacher/course pages. It never asserts that the learner attended or invents a package offer.
- Follow-ups are suppressed after cancellation, opt-out, feedback submission, conversion or dropping. Replies go to `info@recitera.com`; support can set Do not contact. Two-day-old unprocessed acknowledgements/backfilled follow-ups are suppressed.

The existing GitHub Actions worker (Vercel Hobby) checks queues every five minutes, using the restricted signed OIDC identity. Runs are best-effort and can be delayed or disabled by GitHub; exact five-minute-before delivery is not guaranteed. No external credentials or permanent new cron secret are required. Existing configuration/provider/domain must remain operational. No live test emails or charges are needed for local verification.

## Trial outcome and feedback

After the class ends, the linked teacher can report Attended/No show, assessed level and notes from the teacher dashboard. A student/contact can submit a 1–5 rating, comments and Continue/Need guidance/Not continuing from their own account. The server checks booking ownership and the actual end timestamp. Merely passing the end time does not mark attendance. A Not continuing answer opts out of CRM follow-up and records a drop reason for unconverted contacts.

## Initial operational metrics

Lead pipeline cards follow admin filters, including stage, source, owner, trial teacher, campaign, language, opt-out and follow-up dates. Metrics show active leads, contacts with trials, contacts with real paid conversion, their conversion percentage and follow-ups due. Conversion denominator is contacts with recorded trial bookings, not attended sessions; repeat trials do not multiply a contact. Campaign linkage requires the verified enquiry connection. This is an initial operational cohort view, not complete multi-touch attribution. Detailed income remains in the existing permission-protected Financial reports dashboard.

## Next priorities (not implemented in this phase)

2. Separate guardian/payer and child/adult learner entities, longitudinal levels/goals and all-session feedback.
3. Explicit teacher age/gender preferences, ranked timezone/language/availability matching, performance and reassignment cases.
4. Scholarship awards/renewal rules and class-package credit/remaining-session ledgers connected to billing and LMS. Existing discounts, purchases and scholarship applications remain in place.
5. Additional official channels only if requested and configured; current selection is email.
6. Attendance-based conversion cohorts, renewal/churn analytics and reliable campaign attribution beyond the initial pipeline metrics.

Tests cover capture, retries, ownership, signed links/merge, real-vs-test conversion, reconciliation, reminder timing, cancellation/suppression, teacher attendance, student feedback and admin permission/metrics. Frontend browser verification uses isolated mock data; backend tests use local PostgreSQL and the in-memory mail backend.
