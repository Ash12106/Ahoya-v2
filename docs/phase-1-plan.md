# Phase 1 plan: Auth and profiles

**Status:** Approved for implementation on 2026-11-24; self-declared 16+ age-gate collection remains gated on privacy configuration
**Plan date:** 2026-11-24
**Repository:** Ahoya v2, Phase 0 foundation

**Implementation status:** The core sign-in/session and profile slice is implemented. Google sign-in and profile persistence have been confirmed by the user. The user selected a free self-declared 16+ age check instead of third-party verification. DOB collection remains disabled pending the privacy notice, encryption key and backup-retention details. Media, export, deletion and final security/privacy/accessibility reviews remain outstanding.

## Roles

- **ROLE: Product Manager / Business Analyst** — proposes scope, user stories, acceptance criteria and non-goals.
- **ROLE: Solution Architect** — proposes service boundaries, MongoDB documents, session flow and API contracts.
- **ROLE: Agile Delivery Lead** — orders vertical slices, dependencies, review gates and verification work.
- **Required reviewers:** QA, Privacy, Accessibility. Security review is included because the phase handles sign-in, identity data and uploads. Reviews remain pending until recorded below.

Ash approved this plan by saying “ok proceed” on 2026-11-24. Nothing here claims to be an existing product schema or existing profile data. The proposed Phase 1 values are accepted for implementation; live identity-provider and personal-data collection remain gated on the account, notice, and legal requirements listed below.

## Verified starting point

- The configured MongoDB database is reachable and has no product records. The existing security_events, krawl_bans and krawl_counters collections belong to the Phase 0 security foundation.
- The API currently exposes only GET /health and GET /health/db; it has no account, profile, verification or media routes.
- The web app is an empty Phase 0 shell. There is no authentication or profile implementation to preserve.
- Phase 1 must create records only from authenticated user input and verified provider responses. No fixtures, demo users or sample profile content will be used at runtime.

## Objective

Let a person sign in with Google, complete a minimal profile, and pass a self-declared 16+ age check before the age-gated account is considered complete. Do not integrate an external identity provider for this purpose. FastAPI must validate a server-side application session on every protected request. All profile reads and writes use the configured MongoDB database.

### User stories and acceptance criteria

1. **Google sign-in**
   - Given a valid Google sign-in, when Auth.js completes its OAuth/OIDC flow, then the API creates or finds the account using Google’s stable sub claim and creates a revocable application session.
   - Given an invalid, expired, replayed or wrong-audience assertion, when it reaches the API, then no session is created and the response uses the existing generic error envelope.
   - Email is not an account key and accounts are never linked by email alone.
   - Ahoya remains Google-only in this phase. Google handles Google-password recovery; contact email/phone are not account keys or password-reset factors.

2. **Profile registration and edit**
   - Given an authenticated account with no profile, when the age gate is enabled, the owner must submit a valid self-declared date of birth meeting the 16+ minimum along with the required profile fields before the profile is complete.
   - The date of birth is collected only from the user and becomes immutable after its first successful save. The API rejects later changes.
   - Every completed profile has a required username. The API normalizes usernames to lowercase and MongoDB enforces global uniqueness, including concurrent claims; conflicts return `409`.
   - After initial username selection, a user can change it no more than twice in any rolling seven-day period.
   - DOB collection stays optional only while the age gate is disabled. When enabled, the API accepts DOB only when the configured notice is active and the user has recorded consent for that exact notice version.
   - The API rejects future dates and dates that place the user below age 16. This is a self-declared age check, not proof of identity or age.
   - Given an invalid date, unsupported field, oversized value or another user’s identifier, when the request is submitted, then it is rejected and no profile data is changed.
   - The browser sees only the current user’s allowlisted profile fields.

3. **Age eligibility**
   - Age is calculated on the server from the encrypted, self-declared DOB only when the age gate is enabled.
   - Users younger than 16 cannot complete their profile. The API never returns a derived age value or labels the self-declaration as provider-verified.
   - No identity document, Aadhaar data, selfie, or third-party verification response is collected for this age check.

4. **Avatar and cover**
   - Given an authenticated owner, when they upload an image, then the Next.js BFF streams the raw body without buffering it and FastAPI enforces request and slot byte limits at the request boundary before multipart parsing or any R2 write.
   - Only allowed raster images within configured size limits can become active profile media. The server verifies file contents, decodes and re-encodes before activation; extensions and browser MIME claims are not trusted.
   - An incomplete or failed upload never replaces the current image. The profile response is read from MongoDB.

5. **Session and account controls**
   - Given an authenticated session, when the owner signs out and FastAPI is available, then that session is revoked server-side. If revocation cannot be reached, the local cookie is still cleared, the failure is logged without personal data, and the API session expires within the same seven-day maximum.
   - An owner can request an export of their account and profile data and request account deletion, including deletion of profile media and revocation of sessions. Deletion requires recent Google re-authentication evidence bound to a one-time deletion intent, user and session, plus explicit confirmation. Deletion failure at R2 remains retryable and must not silently report success.
   - A stale, missing, wrong-user/session or previously consumed re-authentication proof cannot authorise deletion.

### Accessibility acceptance

- Every sign-in, registration, profile, verification and media control is operable by keyboard, in logical focus order, with a visible, unobscured focus indicator. No flow requires dragging or pointer-only interaction.
- Name and DOB inputs have persistent visible labels and instructions. Invalid, missing, future and unsupported DOB values are associated with their field, announced to assistive technology, and do not rely on colour alone. DOB can be entered with a keyboard and is not restricted to a visual date picker.
- The age field has an accessible label and clear 16+ requirement. Underage, future-date, missing-date and service-unavailable errors are announced without exposing internal details.
- Upload controls have labels and instructions; progress, success, failure and retry status are announced. A failed upload keeps the prior image and offers a keyboard-operable retry.
- Layout supports 200% zoom and reflow at a viewport width of 320 CSS pixels without loss of content or function. Text and controls meet WCAG 2.2 AA contrast requirements; targets meet the 24 by 24 CSS pixel minimum or a documented WCAG exception.
- Sign-out, export and deletion confirmation/status controls meet the same keyboard, focus, labeling and feedback requirements as the account forms.
- An avatar is decorative when the adjacent display name already identifies the account; otherwise it gets concise alternative text. A cover image is decorative by default and uses empty alternative text unless the owner supplies a meaningful description.

## Proposed architecture

1. **Web sign-in:** Auth.js v5 handles Google OAuth/OIDC in Next.js. Configure the provider to require PKCE, state and nonce checks, use the exact configured callback origin, and issue an encrypted HttpOnly session cookie that is Secure in production and SameSite=Lax. The client-visible session object must never include OAuth tokens or the API session token.
2. **Trusted web-to-API handoff:** Auth.js validates Google’s OIDC callback and the Next.js server signs a separate assertion for FastAPI. This is not a Google ID token: FastAPI validates the web-service assertion. It uses EdDSA only, a configured key ID, issuer ahoya-web, audience ahoya-api, Google subject, issue/expiry times, and a unique token ID. Re-auth assertions additionally contain a fixed purpose, the server-validated auth_time, intent ID and current API session ID; none of these values are accepted from browser input. Maximum assertion lifetime is 60 seconds with at most five seconds of clock skew. FastAPI consumes the token ID once in MongoDB. Production traffic uses HTTPS. The private signing key exists only in the web service; FastAPI receives the allowlisted public key or keys. On rotation, the API temporarily accepts active and retiring key IDs for no longer than the assertion lifetime plus skew. No shared Auth.js encryption secret is copied into Python.
3. **API sessions:** FastAPI creates a cryptographically random opaque session token, stores only its SHA-256 hash in MongoDB with owner, creation and expiry timestamps, and returns the raw token only to the Next.js server. Auth.js stores it only inside its encrypted server session. Next.js BFF handlers call FastAPI with it; FastAPI looks up and checks expiry/revocation on every protected request. The Auth.js cookie and API session share a proposed seven-day absolute expiry. Sign-out always clears the local cookie and attempts server revocation first; if FastAPI is unavailable, the web service logs a non-sensitive revocation failure and the inaccessible API token remains usable only until its bounded expiry. This residual risk must be documented and tested. Shared Mongo counters limit session creation to 10 requests per Google subject per 15-minute fixed window and authenticated API traffic to 120 requests per account per minute; counter keys are HMACs and expire through the existing TTL index.
4. **BFF:** Browser requests for account/profile/verification/media operations go through authenticated Next.js route handlers. Those handlers resolve Auth.js with server-side auth(), keep the API token server-side, apply CSRF/origin checks to mutations, and forward only allowlisted input to FastAPI. FastAPI remains the source of truth and reads/writes MongoDB.
5. **MongoDB:** Deletion approval spans intents, re-auth proofs, account status, session revocation and the durable job, so it requires a multi-document transaction. Configure local MongoDB 7 as a single-node replica set. Before enabling any Phase 1 write route or creating Phase 1 indexes, check topology with hello, start a read-only transaction, execute a query against the existing security_events collection through that session, and abort the transaction. An empty result is a successful read; the preflight never requires an existing document or inserts a test record. This performs no application write and verifies that the configured real database can execute a transaction. If the topology check or transactional read fails, keep Phase 1 write routes disabled and fail closed; do not provide a standalone/non-atomic fallback. Use idempotent upserts and unique indexes for sign-in and index creation. Keep R2/provider work outside the transaction and process it only from the committed durable job with idempotent retries. Session expiry is checked in application code as well as cleaned up by a TTL index.
6. **Media storage:** Browser uploads go through the authenticated BFF and FastAPI, not directly to R2. The BFF forwards the raw request stream without calling formData() or arrayBuffer(). An ASGI request-boundary limiter counts incoming bytes before multipart parsing, rejects over-limit Content-Length early and still enforces the streamed limit when Content-Length is missing or false. Decode/re-encode within the accepted limit and write to R2 only after validation. Store object keys and verified metadata in MongoDB. R2 reads remain authenticated during Phase 1; public profile image delivery is deferred until Phase 2 access rules are defined. The current CSP connect-src self remains sufficient for same-origin browser uploads.

Google says to validate signature, issuer, audience and expiry if an ID token is passed to another component, and to use sub rather than email as the stable identifier. This design does not pass Google’s ID token to FastAPI: Auth.js validates the OIDC callback, then FastAPI validates the distinct web-service assertion. See [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect) and [Auth.js session strategies](https://authjs.dev/concepts/session-strategies).

## Proposed MongoDB documents

These are new proposed collections/documents; names and fields are not inferred from the empty database.

| Collection | Minimum proposed fields | Required indexes / controls |
|---|---|---|
| users | _id, google_subject, status, created_at, updated_at | Unique google_subject; never key by email |
| profiles | user_id, username, display_name, encrypted_date_of_birth_self_declared, avatar_asset_id, cover_asset_id, cover_alt_text, created_at, updated_at | Unique user_id and unique lowercase username; field allowlist and date validation |
| auth_sessions | token_hash, user_id, created_at, expires_at, revoked_at | Unique token_hash; TTL on expires_at; check revocation and expiry on every request |
| auth_assertion_replays | jti_hash, expires_at | Unique jti_hash; TTL cleanup; insert must fail on replay |
| account_deletion_intents | intent_id_hash, user_id, session_id, expires_at, consumed_at | Unique intent hash; TTL cleanup; one active intent per session, expires after ten minutes |
| auth_reauth_proofs | proof_hash, intent_id_hash, user_id, session_id, expires_at, consumed_at | Unique proof hash; TTL cleanup; atomically consume once and bind to the current intent/user/session |
| profile_assets | user_id, slot, object_key, content_type, byte_size, status, expires_at, timestamps | Unique object key; owner/slot/status/expiry lookup; pending and replaced assets expire and are cleaned up |
| consent_events | user_id, purpose, scope, notice_version, provider_terms_version, consented_at, withdrawn_at | Purpose-specific consent; no blanket consent; delete with account unless an approved legal exception applies |
| account_deletion_jobs | opaque deletion_id, token_hash, user_id, generated_object_keys, provider_revocations, status, attempts, next_attempt_at, lease_until, timestamps | Atomic worker lease/index; no DOB/name in job; erase user_id/object keys/provider references at completion; retain a minimal completion tombstone for a proposed 30 days |

Self-declared DOB is encrypted at the application layer with authenticated encryption before MongoDB writes. The key is supplied only through deployment/local secrets, includes a key ID for rotation, and has no code default. Age is calculated inside the API to enforce the user-approved 16+ threshold; the derived age is not persisted or returned by GET /v1/auth/me. The comparison treats a February 29 birthday as reaching the next age on March 1 in non-leap years; Privacy/legal review must confirm whether that policy is suitable. This is self-declaration, not verified proof, and no legal-compliance claim is made.

## API contracts

All JSON errors keep the Phase 0 envelope: code, message, request_id. Protected endpoints reject missing, revoked or expired sessions. Backend identifiers are not accepted as authority for a caller’s ownership.

### FastAPI routes

| Method and route | Purpose |
|---|---|
| POST /v1/auth/sessions | Accept a valid one-time assertion from the web service, find/create the Google account, issue an opaque API session. Not called by browser JavaScript. |
| POST /v1/auth/reauth | Accept a one-time web-service assertion carrying Google’s signed auth_time, current session ID and deletion intent; if the same subject authenticated within five minutes, issue a single-use deletion proof returned only to the BFF. |
| GET /v1/auth/me | Return the authenticated account’s onboarding state and profile-completion status. No DOB or derived age status is returned. |
| DELETE /v1/auth/sessions/current | Revoke the caller’s current API session. |
| POST /v1/account/deletion-intents | Create a short-lived deletion intent bound to the authenticated user and current API session; return its raw value only to the BFF. |
| POST /v1/consents | Record a purpose-specific notice/consent event before collecting DOB or starting verification. |
| GET /v1/profiles/me | Read the caller’s profile from MongoDB. Return an explicit empty/incomplete state if no profile exists. |
| PATCH /v1/profiles/me | Create/update allowlisted profile fields, including unique username, display name and cover alternative text; optional self-declared DOB requires an enabled notice and active consent event. |
| POST /v1/verifications/digilocker | Require a separate verification-purpose consent, create an owned attempt and return its provider redirect URL. |
| GET /v1/callbacks/digilocker | Validate one-time state, retrieve provider status/result, persist only approved fields, then redirect to a fixed configured web origin. This distinct static path cannot be confused with an attempt ID route. |
| GET /v1/verifications/digilocker/{attempt_id} | Read the caller’s own verification-attempt status. |
| DELETE /v1/verifications/digilocker/current | Revoke the provider request where supported and remove the current verified result; retain only a minimal withdrawal event. |
| POST /v1/profiles/me/media/{slot_or_asset_id} | With slot avatar or cover, stream the upload through the API; enforce request and file limits before writing to R2; validate/re-encode then activate. |
| GET /v1/profiles/me/media/{asset_id} | Authorise ownership and stream the caller’s active image from private R2 without returning a signed URL. |
| GET /v1/account/export | Return a private, non-cacheable JSON export of account/profile fields, decrypted DOB/name for that owner, verification status, and consent/withdrawal history. Include IDs and authenticated BFF paths for active avatar/cover files; those files remain available through the owner-authorised media read route. |
| DELETE /v1/account | Require body {confirm: true, intent_id, reauth_proof}; verify and atomically consume the proof and matching intent; create one active durable deletion job per account, revoke sessions immediately and return 202 Accepted with an opaque deletion receipt. |
| GET /v1/account/deletions/{deletion_id} | Return deletion status only when the caller presents the matching deletion receipt token. |

### Next.js routes

- Auth.js: GET/POST /api/auth/[...nextauth], including Google sign-in/callback/sign-out handlers.
- BFF: GET/PATCH /api/profile; GET/POST /api/profile/media/{slot_or_asset_id}; POST /api/consents; POST /api/verifications/digilocker; GET /api/verifications/digilocker/{attempt_id}; DELETE /api/verifications/digilocker/current; POST /api/account/deletion-intents; POST /api/account/reauth/google; GET /api/account/export; DELETE /api/account; GET /api/account/deletions/{deletion_id}.
- The export includes all current user-facing account data: profile and DOB values, verified name/DOB and verification state, consent/withdrawal history, and active avatar/cover file access through authenticated media endpoints. It omits OAuth/session secrets, raw provider payloads and security telemetry. Export and media responses use Cache-Control: private, no-store.
- Browser-facing handlers never return the opaque API token, Google tokens, provider secrets, raw verification payloads or MongoDB identifiers beyond what the UI needs.

### Common status behavior

- 200 reads/status, 201 session or verification-attempt creation, 204 successful revocation, and 202 Accepted for a deletion request that is still processing.
- 401 absent/invalid session; 403 authenticated but disallowed; 404 unknown or non-owned resource; 409 state conflict; 422 invalid input; 429 rate limited; 502/503 provider/storage unavailable.
- Use generic public errors and structured server logs with request IDs. Never log cookies, bearer tokens, DOB, full names, callback query strings or provider payloads.

## Age-gate scope

The user selected a free self-declared DOB check with a minimum age of 16. The application collects no identity-provider, Aadhaar, document, or selfie data for this purpose. A user-provided DOB can be false, so the product must describe this as an age check rather than verified age. Keep collection disabled until the exact privacy notice, encryption key and configured-database backup-retention behavior are reviewed. Do not enable an age gate for minors without the required privacy/legal review.

## Media limits and handling proposal

- Avatar: PNG, JPEG or WebP; maximum 5 MiB.
- Cover: PNG, JPEG or WebP; maximum 10 MiB.
- Reject SVG, animated content, malformed/oversized dimensions and unsupported formats. Proposed decoder limits: maximum 25 megapixels and 8192 pixels on either side. Re-encode decoded images before activation; use generated object keys, never user filenames.
- Keep the bucket private. Only the API service receives a scoped R2 key; browser requests remain same-origin through the BFF, so no R2 CORS rule or presigned bearer URL is needed.
- These limits and private-delivery choice are proposals for approval, not existing application behavior.
- Enforce the request-body ceiling before multipart parsing, reject an over-limit Content-Length early, and count bytes while streaming so a missing/false length cannot bypass the cap. Do not write to R2 until the actual bytes are within the slot limit and the decoded/re-encoded image passes validation. The browser uploads same-origin through the BFF; it does not connect directly to R2.
- Rejected or oversized uploads must leave no object in R2 and must not change the current profile asset. Upload tests verify both outcomes against a real or controlled R2-compatible storage test double.

## Proposed retention and consent schedule

This schedule is a proposal for Privacy/legal review and Ash’s approval; production collection remains blocked until the required notice, consent and retention decisions are approved.

| Data | Proposed retention and deletion |
|---|---|
| Self-declared DOB | Encrypted and retained only while the account is active; erased by the account deletion job. |
| Verified name and DOB | Encrypted and retained only while the user keeps verification active; erase on verification withdrawal or account deletion. No copy of the provider payload is stored. |
| Consent events | Keep purpose, scope, notice/provider-terms version, timestamp and withdrawal timestamp while the account is active; erase after deletion unless counsel requires a narrower, documented legal-retention exception. |
| Verification attempts | Pending attempt expires at the provider’s returned expiry. Keep minimal terminal status/provider request reference for 30 days, then TTL-delete. Do not start if the provider supplies no usable expiry. |
| Auth sessions and assertion replay IDs | Maximum seven-day API session; replay record expires at assertion expiry plus five minutes of clock skew. |
| Active media | Retain while selected by the profile. Remove old media when replaced. Pending/abandoned uploads expire after 24 hours. Account deletion removes all object keys before completion. |
| Account-deletion job | Keep no profile PII in the job. Retry until all MongoDB and R2 data are removed; keep a random-ID completion tombstone for 30 days for status checks, then delete it. |
| Export | Stream JSON directly to the authenticated owner with Cache-Control: private, no-store; include consent/withdrawal history and authenticated paths for active media; create no persistent export object or reusable download link. |
| Database backups | Before production, record the actual database backup retention and deletion behavior. Account deletion cannot be reported complete until the documented backup retention implications are disclosed and approved. |

Purpose-specific consent is recorded before DOB collection and separately before the provider redirect. The record includes purpose, scope, notice version, provider terms/version where relevant, timestamp and withdrawal state. The actual notice and consent copy must receive legal review before real people’s DOB or identity data is collected, including in live sandbox testing. Until then, use synthetic or provider-approved test identities only. Do not claim the flow is legally compliant.

The API runs a durable cleanup worker backed by MongoDB. On an accepted account-deletion request, the API snapshots generated R2 object keys and provider request references into the job, immediately makes the account inaccessible, revokes sessions and removes profile/verification/consent/account PII from active MongoDB. The worker atomically claims the job with a lease, revokes provider requests where supported, deletes R2 objects idempotently, clears object/provider references and marks a minimal tombstone complete. The same worker scans expired pending and replaced profile assets, leases them, and deletes their R2 objects and metadata. A crashed process leaves jobs/assets pending; leases expire and another API instance can retry after restart. A deletion receipt is random and stored only as a hash; the BFF holds the raw value in a Secure, HttpOnly, SameSite cookie for up to 30 days so the user can check completion after account sessions are revoked. The deletion screen first creates a short-lived intent bound to the active user and API session. A dedicated Google re-authentication request uses max_age=300 and requests the signed auth_time claim with Google’s claims parameter; the required Google app setting must be enabled. The server verifies the claim is no older than five minutes and belongs to the same Google subject. FastAPI issues a random proof bound to that intent/user/session with a five-minute expiry. The final DELETE request carries confirm=true, intent_id and reauth_proof; one MongoDB transaction atomically consumes the matching proof and intent, creates the durable deletion job, marks the account unavailable and revokes its sessions. Missing, stale, wrong-intent/user/session or replayed proof is rejected, and token iat alone is never treated as proof of fresh authentication. If Google does not return a current auth_time after re-authentication, deletion remains unavailable. Completion means removal from active MongoDB and R2; the approved backup-retention notice must also tell the user when encrypted backups expire. See [Google’s auth_time claim documentation](https://developers.google.com/identity/openid-connect/openid-connect#validatinganidtoken).

DOB and verified name use application-layer authenticated encryption (AES-256-GCM) with key IDs for rotation and unique nonces; authenticated additional data binds each ciphertext to its user and field. Encryption keys are supplied only through local/deployment secret configuration, never MongoDB or source control. Tests must prove that plaintext DOB/name are absent from stored BSON and logs and that missing/wrong key configuration fails closed. Backups remain encrypted; actual backup retention must be confirmed before production.

## Security, privacy and accessibility risks

| Risk | Planned control / open review |
|---|---|
| Forged or replayed login/session | OIDC state/nonce checks; signed, audience-bound, short-lived, single-use web assertion; hashed opaque API sessions; per-request expiry/revocation checks; rate limits. Security reviewer to validate the full trust boundary. |
| Account takeover by email collision | Use Google sub; never auto-link accounts by matching email. |
| OAuth CSRF/open redirect | Exact configured callback URI, single-use state, fixed return origins, Auth.js redirect allowlist, BFF origin/CSRF checks. |
| Child DOB and identity data exposure | Minimise fields, keep verification data separate, no raw documents/payload, field allowlists, no sensitive logs, documented retention and account export/deletion. Privacy review must settle consent, retention and the under-18 legal implications before production use. |
| Unapproved/ineligible KYC use | Provider/account/consent/data-field gate above; no production calls or alternate paid service without approval. |
| Malicious image uploads or orphaned objects | MIME and magic-byte checks, decoder/re-encode, byte/dimension caps, owner-scoped keys, pending state, short expiry, cleanup retry and least-privilege R2 credentials. |
| Accessibility barriers | Keyboard-operable forms, programmatic labels/errors, visible focus, status announcements, redirect return/focus handling, text alternatives for profile images and responsive layouts. Accessibility reviewer to verify against WCAG 2.2 AA. |
| Deletion interrupted by R2 outage | Durable pending deletion state and retryable idempotent cleanup; do not report completion while media remains. |

## Delivery slices and dependencies

1. **Account/session vertical slice:** pinned Auth.js v5 dependency and Google provider; convert local MongoDB to a single-node replica set without resetting its existing foundation collections; verify the configured real DB’s transaction support read-only; signed server assertion; FastAPI session validation; users/auth_sessions indexes; login/logout UI; invalid/replay/expiry tests.
2. **Profile vertical slice:** Mongo-backed profile create/read/edit; incomplete/empty/loading/error states; DOB/display-name validation; authenticated owner checks; no sample runtime data.
3. **Age-gate vertical slice:** require an encrypted self-declared DOB when enabled; enforce the 16+ threshold on the API; show the active notice and record consent; do not use external verification providers.
4. **Media vertical slice:** private R2 configuration, size-limited API streaming, image verification/re-encoding, profile slot update, authenticated read route, orphan cleanup and UI previews. Requires bucket/account details.
5. **Privacy/accessibility/operations slice:** export/deletion lifecycle, retention notes, user-facing consent/status copy marked for legal review, accessible forms, deployment secrets and operational documentation.

Each slice includes its schema/index, API, UI, tests and documentation before it is considered complete. Dependencies are pinned in lockfiles and justified. No paid plan, production traffic, or external service usage that can incur cost is enabled without the user’s approval.

## Verification plan (to run after plan approval and implementation)

- API unit tests for validators and the 16+ calculation; boundary cases for birthdays, leap-day policy, future dates, underage dates and missing DOB.
- Re-auth tests reject missing/old/future auth_time, mismatched Google subject/session, wrong signing key, expired proof, mismatched intent and proof/intent replay; only one active deletion job can be created.
- MongoDB 7 integration tests against a real single-node replica-set container for unique indexes, idempotent account creation, session expiry/revocation, profile ownership, verification state transitions, and transactional deletion-proof/job creation. Verify the read-only transaction preflight leaves security_events unchanged and succeeds when the collection is empty. Also verify that standalone MongoDB disables all Phase 1 writes.
- Abuse cases: unauthenticated/unauthorised calls, forged assertion, wrong algorithm/key ID/issuer/audience, assertion replay, malformed/extra fields, underage or future DOB, repeated requests, oversized upload (assert no R2 object is retained) with missing and false Content-Length, spoofed MIME, invalid image bytes, R2 outage, deletion retry after process restart and sign-out revocation outage.
- Playwright end-to-end coverage of Google login callback with a test provider, 16+ registration/profile edit, upload failure/success mock, logout and deletion UX. Live Google/R2 use is optional and only when credentials exist.
- Automated axe checks run on sign-in, registration/profile, verification and media states. Manual verification covers keyboard-only operation, visible focus, screen-reader announcements/labels, return from provider redirect, 200% zoom and narrow reflow with VoiceOver or NVDA.
- Meet the brief’s minimum 80% coverage for business logic. Do not claim a live-provider verification if only mocks were used.
- Proposed commands, from the repository README: API uv run ruff check app tests, uv run ruff format --check app tests, uv run mypy app, uv run pytest; web npm run lint, npm run typecheck, npm run build, npm run test:e2e; dependency audits from locked files. Commands are not run during this planning step.

## Required configuration after approval

Secrets must be entered locally in the ignored .env or in deployment secret settings, never pasted into chat or committed. The exact names will be reconciled with the actual provider before .env.example is changed.

- Google OAuth client ID/secret and exact authorized callback URL. The re-auth flow requests max_age=300 and Google’s signed auth_time claim. Validate it server-side; if Google does not return a current claim within five minutes, deletion stays disabled rather than falling back to iat or a client timestamp.
- Auth.js secret and the web private/API public key pair for single-use service assertions.
- Canonical web/API origins for exact callbacks and allowlists.
- R2 account ID, private bucket, scoped API access key/secret. No browser CORS configuration, production bucket or paid feature is created by this plan.
- PII encryption keyring and active key ID; assertion signing key and key ID on the web service; matching allowlisted public keyring on FastAPI. Keys are generated/stored as secrets and never pasted into chat.
- MongoDB URI and database name remain the user’s configured real database. Phase 1 creates indexes/documents there only after approval; no seed data.

## Open decisions for review

1. The user selected a 16+ minimum age. Confirm the February 29 birthday convention and review child-safety/privacy obligations for intended markets before enabling collection in production.
3. Approve or change the proposed seven-day API-session lifetime, image limits (5 MiB avatar, 10 MiB cover), transient retention (24-hour abandoned uploads; 30-day terminal attempts and deletion receipt), and deletion/export behavior.
4. Confirm whether profile media should remain private during Phase 1; the plan proposes private delivery until public profile access rules are designed.
5. Provide the actual database-backup retention setting and approve the notice describing backup expiry before production collection is enabled.

## Approval gate

No Phase 1 feature code, dependencies, schema creation or external provider calls begin until:

1. The independent QA, Privacy, Accessibility and Security reviews below are resolved or explicitly recorded as blocked.
2. Ash approves this plan and any listed proposal values.
3. Required external account and origin details are available through local/deployment environment configuration before the corresponding live integration is enabled.

### Independent review record

- QA/Security: final review found no blockers after pre-storage upload limits, private reads, transaction-capable MongoDB, complete re-auth endpoints/proof binding and retryable deletion. Empty security_events preflight wording updated per reviewer.
- Privacy: final review confirms earlier retention/consent/encryption/deletion/age-disclosure/export blockers resolved; no new blocker found. Provider eligibility/legal gates remain.
- Accessibility: final review found no blocker; requested 320 CSS px reflow and account-control coverage, now included.
- Security: reviewed together with QA; final review found no blocker.
- Ash approval: approved on 2026-11-24; implementation approved. On 2026-11-24 Ash selected self-declared DOB age checking with a 16+ minimum instead of a paid/provider verification flow. Real DOB collection remains gated on notice and backup-retention configuration.
