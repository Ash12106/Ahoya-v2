# Ahoya

Ahoya is a fresh-start community platform repository. Phase 0 provides a secure FastAPI and MongoDB API foundation, a clean Next.js shell, local Docker Compose, and CI. It does not import the previous WordPress site.

## Stack

- Web: Next.js 16, React 19, TypeScript, Node.js 24
- API: FastAPI, Python 3.12, PyMongo Async
- Database: MongoDB 7 locally; production provider is to be selected
- Local services: Docker Compose
- Deployment template: Render Blueprint

## Local development

Requirements: Docker Engine with Compose v2. For host-based checks, use Node.js 24 from the [official Node.js downloads](https://nodejs.org/en/download), Python 3.12, and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
cp .env.example .env
docker compose up --build
```

The web app is at `http://localhost:3000`; API health is at `http://localhost:8000/health` and Mongo readiness is at `http://localhost:8000/health/db`. Compose binds both published ports to loopback. MongoDB 7.0.48 is available only on the private Compose network. If port 3000 is already in use, run `WEB_HOST_PORT=3001 CORS_ALLOWED_ORIGINS=http://localhost:3001 docker compose up --build` and open `http://localhost:3001`.

The local API uses the Compose MongoDB by default. To connect it to an existing MongoDB, set `MONGODB_URI` and `DATABASE_NAME` in the root `.env`; Compose passes these only to the API. Keep `.env` untracked. For production, set `MONGODB_URI` in the Render dashboard environment for `ahoya-api`, not in GitHub Actions secrets.

For API development without Compose:

```sh
cd services/api
uv sync --locked --group dev
uv run uvicorn app.main:create_app --factory --reload
```

For web development without Compose:

```sh
cd apps/web
npm ci
npm run dev
```

The `.env.example` values are local-only placeholders. Replace them before sharing the environment. Never use them in deployment.

For Phase 1 Google sign-in, API-session keys, DOB-consent gates, and the available account/profile endpoints, follow [Phase 1 local setup](docs/phase-1-setup.md). Real-person DOB collection is disabled until its notice and key configuration are approved.

## Verification

API checks from `services/api`:

```sh
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest
uv run pip-audit --strict --cache-dir /tmp/ahoya-pip-audit-cache
```

Mongo integration checks require a MongoDB 7 instance:

```sh
TEST_MONGODB_URI=mongodb://localhost:27017/ahoya_test uv run pytest -m integration -o addopts=""
```

Web checks from `apps/web`:

```sh
npm ci
npm run lint
npm run typecheck
npm run audit
npm run build
npx playwright install chromium
npm run test:e2e
```

## Production setup

The Render blueprint intentionally leaves database credentials, secrets, proxy ranges, and CORS origins unset. Production API startup requires all of them. Follow [Cloudflare origin protection setup](docs/security/cloudflare-origin.md) before attaching public DNS or enabling production traffic. The blueprint uses free web-service plans and does not provision a database.

## GitHub Actions images

After a push passes secret scanning, API and web checks, and container builds, GitHub Actions publishes the production images to GitHub Container Registry:

- `ghcr.io/ash12106/ahoya-v2-api`
- `ghcr.io/ash12106/ahoya-v2-web`

Each branch push receives a branch tag and a `sha-...` tag. The `latest` tag is updated only when the default branch passes CI. Pull requests and scheduled checks do not publish images. GHCR package visibility controls who can pull the images; these packages are currently public.

The current packages are public and can be pulled without logging in:

```sh
docker pull ghcr.io/ash12106/ahoya-v2-api:latest
docker pull ghcr.io/ash12106/ahoya-v2-web:latest
```

See the [Phase 0 API contract](docs/api.md) for the verified liveness and MongoDB readiness routes.

## Phase 0 scope

This repository begins from a blank product surface. UI features, identity providers, database provider selection, DNS, Cloudflare rules, and production secrets remain future decisions.

## Data sourcing rule

Runtime product records must come from MongoDB through the API. Do not add seeded or invented product data, in-memory runtime fixtures, or fallback sample records. Until a feature has an agreed schema and API, keep the UI empty or show an explicit empty state. Test doubles belong only in tests.
