# Phase 0 API contract

The Phase 0 API exposes only the health routes required by the approved build plan. Product resources are intentionally absent until their schemas, authorization rules, and source-of-truth collections are defined.

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

## Product routes

No member, profile, group, post, or message endpoint is exposed yet. Adding one requires an agreed MongoDB schema and server-side authorization. Runtime routes must read and write the configured database; test doubles are limited to the test suite.
