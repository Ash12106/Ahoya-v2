# API contract

This page documents the Phase 0 health routes. Phase 1 authentication, profile, consent, and setup endpoints are documented in [Phase 1 local setup](phase-1-setup.md); their data is stored in the configured MongoDB database.

All responses include `X-Request-ID`. Error responses use `code`, `message`, and `request_id`. MongoDB errors are logged by type and returned without connection details.

## `GET /health`

Liveness check for the API process. It does not query MongoDB so an orchestrator can distinguish a live process from a ready service.

Success response:

```json
{"status":"ok","request_id":"<generated request id>"}
```

## `GET /health/db`

Readiness check. It sends a real `ping` command through the configured PyMongo Async client to the configured MongoDB database server.

Success response:

```json
{"status":"ok","request_id":"<generated request id>"}
```

If MongoDB is unavailable, the route returns `503` with the standard error envelope and `DATABASE_UNAVAILABLE` code.

## Later product routes

Group, post, and message endpoints are not exposed yet. Adding them requires an agreed MongoDB schema and server-side authorization. Runtime routes must read and write the configured database; test doubles are limited to the test suite.
