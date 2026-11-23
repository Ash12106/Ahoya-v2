# ADR 0001: Phase 0 application foundation

- Status: accepted for Phase 0
- Date: 2026-11-23

## Context

Ahoya is being restarted in a fresh repository. This phase establishes a deployable API and web shell, local containers, security defaults, and automated checks without bringing forward the previous WordPress site or introducing paid infrastructure.

## Decisions

- Use FastAPI with Python 3.12 and an async PyMongo client. MongoDB deprecated Motor on May 14, 2026 and recommends PyMongo Async for new asynchronous applications.
- Use Next.js as a Render web service so server features and Auth.js route handlers remain available.
- Use MongoDB 7 in local Compose with authentication, a private Docker network, and a persistent volume. Production MongoDB remains an externally provisioned secret because the database provider has not been selected.
- Use Docker multi-stage builds, non-root runtime users, loopback-only local ports, health checks, dropped Linux capabilities, and no-new-privileges.
- Use pinned GitHub Action commit SHAs, locked package dependencies, lint/type/build/test jobs, dependency audits, and secret scanning.
- Require a Cloudflare origin token and verified trusted proxy CIDRs in production. The app is not production-ready until those values and exact origins are configured and tested.
- Start the web UI from a clean shell and keep Phase 0 free of product-specific pages and external paid integrations.

## Consequences

The API intentionally fails closed when production security inputs are absent. The Render blueprint provides an inexpensive starting shape, but it will need real MongoDB credentials, origin secrets, proxy ranges, and the canonical frontend origin before deployment can pass health checks.
