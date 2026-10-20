# Google sign-in

Google OAuth uses authorization code + PKCE (S256), OIDC nonce and a one-time,
ten-minute authorization attempt. The browser is separately bound by a private
HttpOnly/Secure/SameSite cookie. Verifiers are encrypted in PostgreSQL; state and
nonce are stored as digests. State is consumed before external exchange. The
Next.js callback exchanges through Django and sets the existing opaque application
session; Google access/refresh tokens are not stored or exposed to the browser.
Only `openid email profile` are requested. Gmail/mailbox access is not requested.

Django validates Google's signed ID token using pinned google-auth, Google's
trusted issuer/certificates, audience, authorized party, expiry and the original
nonce. Verified email is required. The permanent identity key is Google `sub`,
not a changeable email address. Google-only accounts get unusable passwords.

## Activate on Google Cloud and Vercel

1. Sign in to Google Cloud with the account that owns the application's OAuth
   project. Open **Google Auth Platform** (or APIs & Services → Credentials).
2. Configure Branding with Recitera, an owned support email and `recitera.com` as
   the authorized domain. Public privacy: `https://www.recitera.com/privacy-policy/`;
   terms: `https://www.recitera.com/privacy-policy/#part1`. Use the domain verification
   workflow Google requests if necessary; do not invent verification records.
3. Audience: External for public users. During Testing, add the intended test
   Google accounts as test users. Publish the app when ready for public use and
   complete any verification Google requires.
4. Create **OAuth client → Web application**, then register exact authorized
   redirect URIs:
   - `https://www.recitera.com/api/auth/google/callback`
   - `https://site-pearl-one-38.vercel.app/api/auth/google/callback`
   These belong to Next.js, not the backend or Django admin. The apex redirects
   to www. No JavaScript SDK or browser client secret is needed.
5. Secure backend Vercel `site-backend` production variables:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET` (sensitive)
   - `GOOGLE_REDIRECT_URIS`: comma-separated exact registered callback URLs.
   Defaults include the two production URLs above. Development additionally
   allows localhost:3000; use an explicitly registered localhost URI for a
   different port, only in isolated local development.
6. Redeploy backend after changing credentials. Never put the secret into
   NEXT_PUBLIC variables, frontend source, console logs or chat. The public
   configuration API reveals only whether this request's callback is enabled.
   Without credentials or for an unlisted callback, buttons remain unavailable
   and password-based email login continues to work.

## Existing accounts

Matching email never silently links accounts: an unverified local signup could
otherwise pre-hijack a Google user's account. A returning Google subject signs
into its associated account. For an existing password/email account, sign in with
that password first, then **My account → Connect Google account**. Linking requires
both the original local session and a new browser-bound Google authorization.
It preserves profile, password, teacher links and bookings. A Google identity
cannot be assigned to two users, or replace another connected Google identity.
Disabled accounts cannot log in. Staff can view identities; removal is available
only for accounts that retain a usable password, preventing accidental lockout.

## Verification

Tests exercise actual RSA-signed ID tokens via the Google verification library
with owned certificate fixtures, invalid issuer/audience/nonce/expiry/email,
state replay/expiry, wrong-browser binding, explicit linking and disabled users.
A local browser flow uses an owned provider consent fixture, then real BFF
callback, PKCE attempt and cryptographic verification in Django, application
cookies, signout/returning login, native account linking and CSRF rejection.
These fixtures do not prove live Google consent/login. Actual Google credentials
and a human Google-account authorization are required for that final check.
