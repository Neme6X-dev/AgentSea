# apps/api — Jarvis API

Backend of **Jarvis** — a multi-agent platform that generates showcase (vitrine) websites from a natural-language prompt.

> **This document covers the API only.** It predates the monorepo and parts of it still
> describe the standalone `backend-jarvis` repository. The entry point for the platform
> as a whole is the [repository README](../../README.md); the structural decisions and
> their rationale are in [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md). Where the
> two disagree, those two win.

REST API, PostgreSQL persistence, code/review agents (Gemini), DevSecOps checks, and publishing of static sites. It is consumed by the front-end in `apps/web` and by n8n workflows.

**API docs (local):** http://127.0.0.1:8000/docs  
**Health:** `GET /healthz` → `{"status":"ok","service":"jarvis-api","version":"1.0.0"}`

---

## Table of contents

1. [Overview](#1-overview)
2. [Stack](#2-stack)
3. [Repository layout](#3-repository-layout)
4. [Local development](#4-local-development)
5. [Configuration (environment)](#5-configuration-environment)
6. [API surface](#6-api-surface)
7. [Agents & generation flow](#7-agents--generation-flow)
8. [Database & migrations](#8-database--migrations)
9. [Tests](#9-tests)
10. [Docker image](#10-docker-image)
11. [Production deploy (Wayhost KVM1)](#11-production-deploy-wayhost-kvm1)
12. [CI/CD (GitLab DevSecOps)](#12-cicd-gitlab-devsecops)
13. [Security notes](#13-security-notes)
14. [Related documentation](#14-related-documentation)
15. [Team roles](#15-team-roles)

---

## 1. Overview

```
  apps/web ─────REST──────► apps/api ─────────► PostgreSQL
       │                         │
       │                         ├── Gemini (coder / reviewer / designer)
       │                         ├── sites/<slug>/vN/  (static HTML)
       │                         └── DevSecOps (SAST on publish)
       │
  n8n (Caleb) ──── /api/agents/* (INTERNAL_API_KEY or user JWT)
```

| Concern | Responsibility |
| --- | --- |
| Auth | Local register/login, optional Google / GitHub OAuth, JWT |
| Sessions | Prompt → design → code → review → publish |
| Agents | Async handlers calling Gemini, run by a separate queue worker (not Celery) |
| Sites | Versioned static files under `sites/`, served at `/sites/...` |
| Edge (prod) | Caddy terminates TLS and routes `/api`, `/healthz`, `/sites`, frontend |

---

## 2. Stack

| Area | Choice |
| --- | --- |
| API | FastAPI + Pydantic v2 + Uvicorn |
| DB | PostgreSQL 16 + SQLAlchemy 2 + psycopg 3 + Alembic |
| LLM | Google Gemini (`httpx`), with `GEMINI_MOCK=true` for offline/tests |
| Auth | argon2 passwords, PyJWT (HS256), optional OAuth |
| Deploy assets | Docker multi-stage image, Compose on Wayhost |
| Edge | Caddy 2 (TLS + reverse proxy) |
| CI | GitLab CI — secrets, SAST, SCA, deploy, DAST (**legacy**, see §12) |

---

## 3. Repository layout

```
app/
  main.py              # FastAPI app, CORS, /sites mount, lifespan → init_db()
  config.py            # Settings from environment / .env
  db.py                # SQLAlchemy models + CRUD + Alembic runner
  gemini.py            # LLM client (+ mock)
  contracts.py         # Shared Pydantic schemas
  security.py          # JWT, password hashing, OAuth helpers
  services.py          # Domain orchestration
  routers/             # auth, sessions, chat, agents, deploy, dev
  agents/              # coder, reviewer, designer, templates, n8n designer
  devsecops/           # Local SAST used before publish
migrations/            # Alembic revisions
tests/                 # pytest suite
docs/                  # API.md
Dockerfile             # Build context is the MONOREPO ROOT, not this folder:
                       #   docker build -f apps/api/Dockerfile .
.gitlab-ci.yml         # Legacy: written for the pre-monorepo layout (see repo README)
```

Lives outside this folder, in the monorepo:

```
../../packages/templates/catalog/   # JSON design templates, shared with the front
../../infra/kvm1/                   # Compose, Caddyfiles, deploy.sh, .env.example
../../infra/ci/                     # DefectDojo import helper
requirements.txt
requirements-dev.txt
```

---

## 4. Local development

### Prerequisites

- Python **3.12+**
- PostgreSQL **16** (or Docker)
- Optional: Gemini API key (or keep mock mode)

### Setup

From the **monorepo root**, which knows how to wire all of this together:

```bash
make install      # venv + deps + .env, for API and front
make db-dev       # PostgreSQL on host port 55432, with the test database
make migrate
```

Then edit `apps/api/.env` — at minimum `JWT_SECRET`, `INTERNAL_API_KEY`, `DATABASE_URL`.

Port **55432**, not 5432: a development machine almost always already runs another
PostgreSQL on the standard port, and a suite that silently connects to a neighbouring
project's database is worse than one that refuses to start.

### Run

```bash
make api          # uvicorn, auto-reload, port 8000
make worker       # a queue worker, in a second terminal
```

`JOB_MODE=inline` in `.env` runs generations in the web process instead, which saves
that second terminal in development. Never in production.

By hand, from this folder: `./run.sh` (creates the venv, generates missing secrets,
applies migrations, starts uvicorn).

- OpenAPI UI: http://127.0.0.1:8000/docs  
- Health: http://127.0.0.1:8000/healthz  

The Vite dev server in `apps/web` proxies `/api` and `/sites` here by default.

---

## 5. Configuration (environment)

Never commit real secrets. Template: [`.env.example`](.env.example) (production : [`infra/kvm1/.env.example`](../../infra/kvm1/.env.example)).

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres URL. Inside Compose: `postgresql://USER:PASS@db:5432/sites` (password **must** match `POSTGRES_PASSWORD`) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Compose DB service (password only set on **first** volume init) |
| `APP_PORT` | Uvicorn listen port in container (**8080** in prod) |
| `PUBLIC_BASE_URL` | Public origin used in `site_url` links (e.g. `https://e-segmentation-victory.sacha-epitnet.tech`) |
| `DOMAIN` | Caddy site address (hostname or `:80` for HTTP-only) |
| `JWT_SECRET` | HS256 signing key |
| `INTERNAL_API_KEY` | Service bearer for n8n / `/api/agents/*` |
| `GEMINI_API_KEY` / `GEMINI_MOCK` | Real Gemini vs deterministic mock |
| `CI_REGISTRY_IMAGE` / `APP_TAG` | App image for Compose |
| `FRONTEND_IMAGE` / `FRONTEND_TAG` | Nginx frontend image |
| `DEPLOY_MODE` | `registry` (pull images) or `local` (build app on VPS) |
| `CI_REGISTRY` / `CI_REGISTRY_USER` / `CI_REGISTRY_PASSWORD` | Registry login for pulls |

**Important:** special characters in DB passwords must be URL-encoded inside `DATABASE_URL`.

---

## 6. API surface

Interactive contract: `/docs`. Written reference: [`docs/API.md`](docs/API.md).

| Prefix | Role |
| --- | --- |
| `/api/auth/*` | Register, login, OAuth, `me` |
| `/api/sessions/*` | Create/list/get sessions, publish |
| `/api/chat/*` | Conversational framing of the brief |
| `/api/agents/*` | Agent steps (n8n / internal) |
| `/api/dev/*` | Dev helpers to run the pipeline |
| `/api/deploy` | Deploy helpers |
| `/healthz`, `/api/health` | Liveness (no DB) |
| `/sites/<slug>/…` | Generated static sites |

Auth header: `Authorization: Bearer <JWT|INTERNAL_API_KEY>`.

Quick smoke:

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"MotDePasse123!","name":"Demo"}'
```

---

## 7. Agents & generation flow

Agents run in a **separate worker process** (`python -m app.jobs.worker`), which picks
jobs off a durable PostgreSQL queue. They used to run inline in the FastAPI process;
that is now only the `JOB_MODE=inline` development shortcut. A generation takes 60–180 s,
which is why it cannot stay on the web event loop — see `docs/ARCHITECTURE.md` §1.

Typical path:

1. User creates a **session** with a prompt (`POST /api/sessions`).
2. **Chat / designer** may refine a design spec (templates or Gemini / n8n designer).
3. **Coder** generates HTML/CSS/JS into `sites/<slug>/vN/`.
4. **Reviewer** scores the artefact (local SAST + heuristics / Gemini).
5. **Publish** promotes a version to `live/` when quality gates allow.

Orchestration can be driven by the frontend, `/api/dev/*`, or n8n calling `/api/agents/*`.

In production the queue mode implies **at least one worker in service**. Without it the
API keeps accepting requests, keeps stacking rows in `jobs`, and keeps reporting
healthy — while every client session stays "in progress" forever. The Compose stack
therefore ships a `worker` service alongside `app`, and `deploy.sh` fails the deploy if
it is not running.

---

## 8. Database & migrations

- Schema is owned by **Alembic** under `migrations/`.
- On container start, lifespan calls `init_db()` → `alembic upgrade head`.
- There is **no** silent `create_all()` fallback (avoids schema drift without `alembic_version`).

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

---

## 9. Tests

```bash
make db-dev && make test-api      # 225 tests
```

The suite requires a **real PostgreSQL**: the schema relies on types and locks
(`SKIP LOCKED`) that SQLite does not reproduce, and a test database that lies about
production behaviour tests nothing. `conftest.py` fails with an explicit message rather
than silently falling back.

---

## 10. Docker image

The build context is the **monorepo root**, not this folder:

```bash
docker build --platform linux/amd64 --provenance=false --sbom=false \
  -f apps/api/Dockerfile -t jarvis-api:<tag> .
```

The image copies `packages/templates/catalog/` — the shared template catalog — which
lives outside `apps/api/`. Building from this folder produces an image that starts,
passes its healthcheck and generates sites, but where `catalog()` returns an empty
tuple and the coder works with no structural reference. Nothing logs it.

- Listens on **8080** inside the image.
- Runs as non-root `appuser` (uid 10001). Bind-mounted `data/` and `sites/` must be owned by that uid on the VPS (`deploy.sh` handles this).
- The `worker` service reuses this same image with `command: python -m app.jobs.worker`.

---

## 11. Production deploy (Wayhost KVM1)

**Host:** `45.93.21.45` · **SSH user:** `emmy`  
**Paths:** `/opt/app` (Compose + `.env` + Caddy), `/opt/src/agentsea` (monorepo source for local builds)

### Stack (Compose)

| Service | Image / role |
| --- | --- |
| `db` | `postgres:16-alpine` |
| `app` | `CI_REGISTRY_IMAGE:APP_TAG` (this backend) |
| `worker` | Same image, `python -m app.jobs.worker` — drains the `jobs` queue |
| `web` | `FRONTEND_IMAGE:FRONTEND_TAG` (`apps/web` nginx image) |
| `edge` | `caddy:2-alpine` — TLS, `/api` → app, `/` → web, `/sites` → volume |

Full procedure: [`infra/kvm1/README.md`](../../infra/kvm1/README.md).

### Registry mode (preferred)

On your Mac:

```bash
cd backend-jarvis
IMAGE=registry.itnet-technologies.fr/segmentationvictory/backend-jarvis
TAG=$(git rev-parse --short HEAD)
docker login registry.itnet-technologies.fr
docker build --platform linux/amd64 --provenance=false --sbom=false \
  -t "${IMAGE}:${TAG}" -t "${IMAGE}:latest" .
docker push "${IMAGE}:${TAG}" && docker push "${IMAGE}:latest"
```

Sync deploy assets and on the VPS:

```bash
cd /opt/app
# DEPLOY_MODE=registry
# CI_REGISTRY_IMAGE=registry.itnet-technologies.fr/segmentationvictory/backend-jarvis
# APP_TAG=<tag>
# FRONTEND_IMAGE=registry.itnet-technologies.fr/segmentationvictory/frontend-jarvis
# FRONTEND_TAG=<front-tag>
# DOMAIN=e-segmentation-victory.sacha-epitnet.tech
# PUBLIC_BASE_URL=https://e-segmentation-victory.sacha-epitnet.tech
./deploy.sh
curl -fsS https://e-segmentation-victory.sacha-epitnet.tech/healthz
```

### Caddy profiles

| File | When |
| --- | --- |
| `Caddyfile` | Production TLS (`{$DOMAIN}` + Let’s Encrypt) |
| `Caddyfile.http-dev` | HTTP only (`:80`) while DNS/TLS unavailable |
| `Caddyfile.tls-internal` | HTTPS with Caddy local CA (browser warning) |

Wayhost **security group** must allow inbound TCP **22**, **80**, **443**. Prefer SG over local UFW.

### After `.env` changes

```bash
cd /opt/app && docker compose up -d
```

Containers do not reload env until recreate. Changing `POSTGRES_PASSWORD` does **not** update an existing volume — keep `DATABASE_URL` in sync with the password used at first init, or recreate the volume (`docker compose down -v`).

---

## 12. CI/CD (GitLab DevSecOps)

> ⚠️ **This pipeline does not currently run.** `.gitlab-ci.yml` was written when this
> folder *was* the repository root: it references `Dockerfile` and `deploy/kvm1/` at the
> root, which are now `apps/api/Dockerfile` and `infra/kvm1/`. Its `deploy_wayhost` job
> is additionally gated on `exists: [Dockerfile]` at the root — so on the monorepo it is
> silently skipped rather than failing. The repository itself now lives on GitHub, where
> this file is never read at all.
>
> Deployment is therefore **manual** (`infra/kvm1/deploy.sh`) until the pipeline is
> ported. The description below documents the intended design, not the current state.

Pipeline (`.gitlab-ci.yml`) maps to J2 qualification:

| Stage | Jobs (examples) |
| --- | --- |
| `test` | `unit_tests` (pytest + Postgres) |
| `security` | Secret Detection, **Gitleaks**, **SAST** (Semgrep/Bandit), Dependency Scanning |
| `build` | Image build (Kaniko) — currently `when: never` (push from Mac) |
| `policy` | Checkov on Dockerfile / Compose |
| `deploy` | `deploy_wayhost` → rsync + `./deploy.sh` on `main` |
| `dast` | GitLab **DAST** against the live site |

### Required CI/CD variables

| Variable | Notes |
| --- | --- |
| `WAYHOST_HOST` | `45.93.21.45` |
| `WAYHOST_SSH_PRIVATE_KEY` | Type **File**, private key for `emmy@` |
| `DOMAIN` | `e-segmentation-victory.sacha-epitnet.tech` |
| `DAST_TARGET_URL` | Optional; defaults to the HTTPS site URL |

---

## 13. Security notes

- Do not commit `.env`, JWT secrets, or API keys.
- Rotate any secret that appeared in chat, tickets, or git history.
- Publish path runs local SAST; weak reports can block auto-publish (see session/publish logic).
- Agents do not port-scan; reviewer SAST is local analysis of generated files.

---

## 14. Related documentation

| Doc | Content |
| --- | --- |
| [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) | Full architecture (FR) |
| [`docs/API.md`](docs/API.md) | API contract for front + n8n |
| [`infra/kvm1/README.md`](../../infra/kvm1/README.md) | Short VPS ops checklist |
| [`docs/security-policy.md`](../../docs/security-policy.md) | Security practices |
| [`docs/coding-rules.md`](../../docs/coding-rules.md) | Coding conventions |

---

## 15. Team roles

| Role | Focus |
| --- | --- |
| **Flo** | This backend, agents, API, DevSecOps in-app |
| **Caleb** | Designer agent + n8n orchestration |
| **Emmy** | VPS, Caddy, registry, CI deploy, secrets |
| **Front** | [Frontend-Jarvis](https://gitlab.itnet-technologies.fr/segmentationvictory/Frontend-Jarvis) |

---

## License / school context

Built for the ITNET **Segmentation Victory** project (prototype + DevSecOps qualification). Internal GitLab: `segmentationvictory/backend-jarvis`.
