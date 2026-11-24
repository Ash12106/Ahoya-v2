# Phase 1 local setup

Phase 1 stores account and profile records in the configured MongoDB database. It does not create demo users or sample profiles. MongoDB must support replica-set or sharded transactions; `/health/phase1` reports whether the API's read-only transaction preflight passed.

## API endpoints available in this slice

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | API liveness |
| `GET` | `/health/db` | MongoDB connectivity |
| `GET` | `/health/phase1` | Transaction and Phase 1 write readiness |
| `POST` | `/v1/auth/sessions` | Web-service-only exchange of a signed assertion for a revocable API session |
| `GET` | `/v1/auth/me` | Current account and profile-completion status, without DOB or derived age; profile completion requires an eligible DOB when the age gate is enabled |
| `DELETE` | `/v1/auth/sessions/current` | Revoke the current API session |
| `GET` | `/v1/profiles/me` | Read the signed-in user's profile from MongoDB |
| `PATCH` | `/v1/profiles/me` | Save a unique username, display name, and cover description; when enabled, also requires consented self-declared DOB meeting the 16+ minimum |
| `POST` | `/v1/consents` | Record versioned DOB consent before accepting DOB data |

Browser code calls the Next.js BFF (`/api/profile`, `/api/consents`). It never receives the API bearer token. `/v1/auth/sessions` accepts only a short-lived EdDSA assertion from the web service and must not be called by browser JavaScript.

Usernames are required during profile setup, stored in lowercase, and unique across profiles. Use 3–24 ASCII letters, numbers, or underscores. MongoDB enforces uniqueness, including concurrent profile updates; a conflict returns HTTP `409` with code `USERNAME_UNAVAILABLE`. After the initial username selection, users can change it at most twice in a rolling seven-day period; further changes return `429 USERNAME_CHANGE_LIMIT` and a `Retry-After` header.

API docs are available at `/docs` only outside production.

Session creation is limited to 10 requests per Google subject per 15-minute window. Authenticated API traffic is limited to 120 requests per account per minute. Limits are stored in MongoDB so they apply across API processes; rejected requests return `429` and a `Retry-After` header.

## Google sign-in

Set these values in the ignored root `.env` file before using Docker Compose:

```dotenv
AUTH_URL=http://localhost:3000
AUTH_SECRET=replace_with_output_from_openssl_rand_base64_32
AUTH_GOOGLE_ID=replace_with_Google_OAuth_client_ID
AUTH_GOOGLE_SECRET=replace_with_Google_OAuth_client_secret
```

Add this exact callback to the Google OAuth client: `http://localhost:3000/api/auth/callback/google`. If the web app uses another local host port, update both `AUTH_URL` and Google's callback URL to that exact origin. Keep the Google secret in local/deployment secrets; never paste it into chat or commit it.

Generate the Ed25519 web-to-API key pair from `apps/web`:

```sh
node scripts/generate-api-keys.mjs
```

Copy the three output assignments into the ignored root `.env`. `API_ASSERTION_PRIVATE_KEY` and `API_ASSERTION_KEY_ID` are consumed by the web service. `WEB_ASSERTION_PUBLIC_KEYS` is consumed by FastAPI. Keep the JSON value quoted in `.env` if your shell or Compose parser requires it. On key rotation, add the new public key to the API JSON map before switching the web key ID, and retain the old public key until old assertions can no longer be valid.

`AUTH_SECRET` is separate from the Ed25519 key. Use a distinct value for each deployment. The web service must have `API_INTERNAL_ORIGIN=http://api:8000` in Compose; for host-based Next.js development use `http://127.0.0.1:8000` in the web app's local environment.

This implementation pins Auth.js v5 at `5.0.0-beta.32`; the current npm v5 distribution remains on a beta tag. Reassess that dependency before production release.

Ahoya remains Google-only sign-in, with no Ahoya password to reset. Users recover a forgotten Google password through Google. Contact email and phone are not account keys or recovery methods in this phase; do not link an account by email or phone alone.

## Self-declared 16+ age gate

The age check uses the date a user enters during initial profile setup. It is self-declared and does not prove identity or independently verify age. The API enforces the minimum age of 16 when collection is enabled; the browser's date limit is only a usability aid. After the first successful save, the date of birth is immutable: the form locks the field and the API rejects attempts to change it with `409 DATE_OF_BIRTH_LOCKED`. Age is calculated on the server and is never included in the account status response. A February 29 birthday reaches the next age on March 1 in non-leap years; have this policy reviewed for the markets Ahoya serves.

Date-of-birth collection remains disabled by default. Leave `DOB_COLLECTION_ENABLED=false` until the privacy notice and consent copy are reviewed, the encryption key is configured, the February 29 policy is accepted, and the actual database backup-retention behavior is documented. To enable it after those reviews, configure all of:

```dotenv
PII_ENCRYPTION_KEYS='{"pii-2026-01":"<base64 of a random 32-byte key>"}'
PII_ENCRYPTION_ACTIVE_KEY_ID=pii-2026-01
DOB_COLLECTION_NOTICE_VERSION=replace_with_reviewed_notice_version
DOB_COLLECTION_NOTICE_TEXT="replace_with_reviewed_notice_text"
DOB_COLLECTION_ENABLED=true
```

Generate a 32-byte key locally with `openssl rand -base64 32`. Keep encryption keys in the secret manager and preserve old keys while data encrypted with them remains. The application uses the keyring for DOB and private contact details with AES-256-GCM; it refuses DOB collection if the active key, notice version, or notice text is missing or invalid. Do not send the generated key or notice text to chat. Stored personal data must be included in the approved retention and deletion policy.

## Local MongoDB transactions

Compose starts MongoDB 7 as a single-node replica set. The initialization preserves the existing `mongo_data` volume; it does not drop the database. The API checks `hello`, then performs a read-only transaction query against `security_events` and explicitly aborts it before creating Phase 1 indexes. Empty results count as a successful check. If the configured database does not support transactions, account/profile writes stay disabled.

When `MONGODB_URI` points to Atlas, the API runs the same preflight against the configured database. Keep the URI only in `.env` or deployment secrets. The local Compose Mongo service may still run for development but does not replace that configured URI.

## Not enabled yet

Google sign-in requires the OAuth credentials and signing key pair above. DOB registration remains disabled until the notice, encryption and backup-retention gates are met. No identity-provider integration is used for the age check. R2 media requires a Cloudflare account ID, private bucket name, and bucket-scoped access key/secret in local or deployment secrets. No sample profiles or age claims are fabricated. Account export/deletion and the re-authentication flow are still in implementation and are not advertised as available endpoints in this slice.
