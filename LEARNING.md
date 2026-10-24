# Recorded courses and packages

## Admin workflow

1. Open **Academy → Recorded courses**, add or edit a course and choose **Recitera platform** as its delivery mode.
2. Set title, teacher, description, optional cover and price in CAD. A price of zero makes the whole course free.
3. Add episode rows, or manage them under **Episode videos**. Set title, order, duration (optional), publication status and whether each episode is a free preview.
4. Select a video provider:
   - **Vimeo**: paste an HTTPS video/player URL. Unlisted videos must include their privacy hash.
   - **Direct video / other host**: paste a direct HTTPS media URL from a hosting account, CDN or storage provider. MP4 and WebM play using the browser's native video player. Browser-supported stream formats may also play; a normal web page or iframe HTML is not a direct media URL.
5. Publish the course when its episodes are ready. A paid course may contain any number of free-preview episodes; other episodes unlock after purchase.

Provider privacy still needs to be configured at the media host. For Vimeo, allow embeds on the production Recitera domains and retain unlisted hashes. For direct hosting, use the provider's private/signed delivery controls where appropriate and provide browser-playable HTTPS media with correct content type/range support. The application gates playback URLs by enrolment; arbitrary host URLs are not DRM.

Existing external academy courses keep their original delivery mode and links. To move one onto this platform, change its delivery mode, add the real episode video URLs and publish. No fake video IDs or production demo courses are created by deployment.

## Packages and promotions

Under **Course packages**, select published Recitera-platform courses and enter a package discount percentage. The price is calculated from the current course prices minus that percentage. Empty, mixed-currency or external-course packages cannot be published for native checkout. Buying a package adds every included course to the purchaser's library.

The **Discount codes** screen also supports packages, alongside courses, teachers' classes and payment-page products. A coupon applies to the package's already-discounted price. One coupon is allowed per checkout; eligibility and minimum amounts are checked by the backend.

The course list included in each order is captured at checkout. Later edits to a package do not change what its previous purchaser receives.

## Learner experience

- `/courses`: course catalogue and available packages.
- `/courses/<slug>`: curriculum, free previews, access status and course player.
- `/packages/<slug>`: included courses, original/package price and enrolment.
- `/account/courses`: the signed-in learner's enrolled courses, completion percentage and approximate viewing time.

Free courses/packages can be added to an account without a card. Paid checkout requires a signed-in account and takes its buyer identity from the verified session, not an entered email. Access is granted only by a validated Stripe webhook, or immediately for a fully discounted zero-balance order. Enrolment is idempotent. Inactive/revoked access cannot be repurchased accidentally.

Video addresses are absent from public course/episode listings. A separate playback request checks course visibility and learner access before returning a Vimeo player address or direct media URL. Free previews remain public. Archived courses remain available to their enrolled users while published episodes remain present.

Both video players save position and playback activity periodically. Learners may explicitly mark an episode complete. Completion is personal study tracking, not an examination result. The library calculates completion from published episodes, and the player resumes incomplete lessons. Progress updates are account-scoped, bounded, rate-limited and do not grant access to paid content.

## Payments, migrations and operations

Course purchases use the existing signed Stripe webhook and encrypted connection settings. Original and discounted prices remain recorded on the order. Class booking and donation paths are retained. A one-time `LEARNING_CONFIGURE=true` build flag enables recorded-course payments using `configure_learning`; the operator should remove this flag after the initial deployment so later admin changes are respected.

Migrations preserve legacy external courses and existing purchases. Existing guest payment records are not silently turned into account entitlements based on an unverified email.

`learning.tests` covers public/paid playback separation, direct/Vimeo URL validation, authenticated buyer identity, webhook amount verification, free enrolment, full coupons, package price/access snapshots, per-user progress and revoked access. Browser verification uses an isolated PostgreSQL database and local media fixtures; no real charges or production demo records are needed.

## Importing the existing twelve Surah courses

`learning/recorded_course_import.json` maps the twelve user-supplied Vimeo video IDs to the existing catalogue in the supplied order. Playback URLs are intentionally empty: Vimeo Review share tokens are not unlisted playback hashes, and must not be substituted into player URLs. Obtain each video's Share/Embed URL from Vimeo, confirm embedding is permitted on the Recitera domain, then populate `video_url` in a private working copy of the manifest. Do not commit private Review tokens.

Validate with `python manage.py import_recorded_courses /path/to/manifest.json`. After checking the video-to-course mapping and playback, run the same command with `--apply` against the production database. The import validates every entry before any write, preserves current prices, teachers, descriptions, publication settings and old external URLs, and switches delivery to the internal course page. Repeating the import does not duplicate episodes; conflicting videos or existing multi-episode curricula require manual review in admin. This command is intentionally not part of the build, so subsequent admin edits are not overwritten.

The twelve existing Surah courses now use internal delivery. Migration `learning.0003` clears their academy links and creates one unpublished, empty-video episode only where no curriculum exists; prices, teacher assignments and existing episodes are preserved. New installations seed the same internal courses with draft episodes. In admin, edit **Episode videos**, enter the Vimeo Share/Embed URL or direct media URL, then enable **Published**. Empty-video drafts are allowed, but publishing them is rejected. Courses with no published episodes remain visible with enrolment closed.
