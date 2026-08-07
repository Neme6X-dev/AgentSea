# Frontend-Jarvis

Web UI for **Jarvis / Segmentation Victory** — the French-language dashboard where users authenticate, describe a business, follow multi-agent generation in a 3D scene, preview generated sites, and manage projects.

This repo talks to [backend-jarvis](https://gitlab.itnet-technologies.fr/segmentationvictory/backend-jarvis) over REST (`/api/*`). In production it is shipped as an **nginx Docker image** and exposed by Caddy on the Wayhost VPS.

**Production:** https://e-segmentation-victory.sacha-epitnet.tech  
**Local dev:** http://127.0.0.1:5173 (Vite, proxies API to the backend)

---

## Table of contents

1. [Overview](#1-overview)
2. [Stack](#2-stack)
3. [Pages & features](#3-pages--features)
4. [Repository layout](#4-repository-layout)
5. [Local development](#5-local-development)
6. [Configuration](#6-configuration)
7. [Talking to the backend](#7-talking-to-the-backend)
8. [Build](#8-build)
9. [Docker image (registry mode)](#9-docker-image-registry-mode)
10. [Production deploy](#10-production-deploy)
11. [CI/CD (GitLab DevSecOps)](#11-cicd-gitlab-devsecops)
12. [3D scene & assets](#12-3d-scene--assets)
13. [Troubleshooting](#13-troubleshooting)
14. [Related projects](#14-related-projects)

---

## 1. Overview

```
  Browser
     │
     ▼
  Caddy (edge) ──► web (nginx / this image)   ← HTML/JS/CSS
                 ──► app (backend-jarvis)      ← /api/*, /sites/*
                 ──► sites volume             ← generated vitrines
```

| Concern | Implementation |
| --- | --- |
| UI | Multi-page app (MPA): real `.html` files, no client-side router |
| Styling | Tailwind CSS 3 |
| 3D | three.js + Draco + navmesh (agent progress visualization) |
| Auth | JWT stored in the browser; calls `/api/auth/*` |
| API | `src/lib/api.js` + `apiUrl()` from `src/lib/config.js` |

---

## 2. Stack

| Area | Choice |
| --- | --- |
| Bundler | Vite 7 (`appType: 'mpa'`) |
| Language | JavaScript (ES modules) |
| CSS | Tailwind 3 + PostCSS |
| 3D | `three`, Draco decoder under `public/assets/draco/` |
| Prod server | `nginx:1.27-alpine` (see `Dockerfile` + `nginx.conf`) |
| CI | GitLab — build, Gitleaks, SAST, deploy, DAST |

---

## 3. Pages & features

| Page | File | Role |
| --- | --- | --- |
| Accueil | `index.html` | Landing / entry |
| Connexion | `connexion.html` | Login / register / OAuth entry |
| Projets | `projets.html` | List user sessions |
| Éditeur | `editeur.html` | Prompt, chat framing, preview/code tabs, publish |
| Agents | `agents.html` | 3D agent progress scene |
| Ressources | `ressources.html` | Resources / help content |
| Paramètres | `parametres.html` | User settings |
| Aide | `aide.html` | Help |

Editor highlights:

- Conversational briefing via `/api/chat`
- Live step tracking from session payload
- Preview iframe for `/sites/<slug>/…`
- 3D agents scene synced with generation progress

---

## 4. Repository layout

```
*.html                 # MPA entry points (Vite inputs)
src/
  main.js              # Shared boot
  lib/
    api.js             # HTTP helpers
    auth.js            # Token / session helpers
    config.js          # API_BASE_URL, apiUrl, previewUrl
    agent-progress.js  # Progress model for the 3D scene
  pages/               # Per-page controllers (editeur, projets, …)
  scene/               # three.js agents scene + navmesh
  styles/
public/                # Static assets copied as-is (models, draco, …)
Dockerfile             # node build → nginx
nginx.conf             # try_files for MPA + cache for static
.gitlab-ci.yml
package.json
vite.config.js
tailwind.config.js
```

---

## 5. Local development

### Prerequisites

- **Node.js 22+** (CI uses 22)
- Running **backend-jarvis** on `http://127.0.0.1:8000` (or set the proxy target)

### Install & run

```bash
cd Frontend-Jarvis
npm ci
npm run dev
```

Open http://127.0.0.1:5173.

Vite proxies (see `vite.config.js`):

| Path | Target (default) |
| --- | --- |
| `/api` | `http://127.0.0.1:8000` |
| `/sites` | `http://127.0.0.1:8000` |

Override proxy with `VITE_API_PROXY_TARGET` if the API is elsewhere.

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8080 npm run dev
```

Leave `VITE_API_BASE_URL` **empty** in local dev so the browser calls same-origin `/api/...` through the proxy (no CORS preflight).

---

## 6. Configuration

| Variable | When | Meaning |
| --- | --- | --- |
| `VITE_API_BASE_URL` | Build-time | Public API origin **without** trailing slash. Empty = relative `/api` (recommended behind Caddy). |
| `VITE_API_PROXY_TARGET` | Dev only | Where Vite proxies `/api` and `/sites`. |

Example production build with explicit API origin (usually unnecessary if Caddy serves front + API on one host):

```bash
VITE_API_BASE_URL=https://e-segmentation-victory.sacha-epitnet.tech npm run build
```

Preferred production setup: **empty** `VITE_API_BASE_URL` so the UI uses `https://<domain>/api/...` on the same host as the SPA.

---

## 7. Talking to the backend

```js
import { apiUrl, previewUrl } from './lib/config.js';

// Relative in prod behind Caddy: /api/sessions
fetch(apiUrl('/api/sessions'), {
  headers: { Authorization: `Bearer ${token}` },
});

// Rewrite backend site_url (often localhost in LOCAL backend config) to same origin
iframe.src = previewUrl(session.site_url);
```

Auth flows hit `/api/auth/register`, `/api/auth/login`, optional Google/GitHub.  
Sessions and publish use `/api/sessions`. Chat uses `/api/chat`.

Full API contract: backend [`apps/api/docs/API.md`](../api/docs/API.md).

---

## 8. Build

```bash
npm ci
npm run build    # → dist/
npm run preview  # optional local preview of dist
```

Notes from Vite config:

- Outputs JS/CSS under `dist/bundle/` so they do not clash with `public/assets/`.
- Each HTML page is its own Rollup input (true MPA).
- `three` is code-split; loaded when a 3D page mounts.

---

## 9. Docker image (registry mode)

```dockerfile
# Multi-stage: npm run build → nginx:alpine serving /usr/share/nginx/html
```

Build & push (ITNET registry), same pattern as the backend:

```bash
cd Frontend-Jarvis
IMAGE=registry.itnet-technologies.fr/segmentationvictory/frontend-jarvis
TAG=$(git rev-parse --short HEAD)

docker login registry.itnet-technologies.fr
docker build --platform linux/amd64 --provenance=false --sbom=false \
  -t "${IMAGE}:${TAG}" -t "${IMAGE}:latest" .
docker push "${IMAGE}:${TAG}"
docker push "${IMAGE}:latest"
```

`nginx.conf` uses:

```nginx
try_files $uri $uri/ $uri.html /index.html;
```

so `/editeur`, `/editeur.html`, and static assets all resolve correctly.

---

## 10. Production deploy

Frontend runs as Compose service **`web`** on the VPS (`/opt/app`), pulled from the registry. Caddy reverse-proxies `/` → `web:80`.

### On the VPS (`/opt/app/.env`)

```env
FRONTEND_IMAGE=registry.itnet-technologies.fr/segmentationvictory/frontend-jarvis
FRONTEND_TAG=<short-sha>
DEPLOY_MODE=registry
# … plus backend DB/registry vars from backend-jarvis
```

### Roll frontend only

```bash
cd /opt/app
sed -i "s|^FRONTEND_TAG=.*|FRONTEND_TAG=<short-sha>|" .env
# login to registry if needed (CI_REGISTRY_* in .env)
docker compose pull web
docker compose up -d --no-deps --force-recreate web
docker compose up -d --no-deps edge
```

Or full stack: `./deploy.sh` (pulls `app` + `web` + `db` + `edge` in registry mode).

### Verify

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" https://e-segmentation-victory.sacha-epitnet.tech/
curl -fsS https://e-segmentation-victory.sacha-epitnet.tech/healthz   # backend via Caddy
```

**Do not** overwrite the live TLS `Caddyfile` with `Caddyfile.http-dev` on a working HTTPS host.

---

## 11. CI/CD (GitLab DevSecOps)

`.gitlab-ci.yml` stages:

| Stage | Purpose |
| --- | --- |
| `test` | `unit_build` — `npm ci` + `npm run build` |
| `security` | Gitleaks, **SAST** (GitLab + Semgrep), dependency scanning |
| `build` | Artifact / optional Kaniko image (`when: never` → push from Mac) |
| `deploy` | SSH to VPS, set `FRONTEND_TAG`, `docker compose pull web` |
| `dast` | Dynamic scan of the live URL |

### CI/CD variables (Frontend-Jarvis project)

| Variable | Required | Notes |
| --- | --- | --- |
| `WAYHOST_HOST` | Yes (deploy) | `45.93.21.45` |
| `WAYHOST_SSH_PRIVATE_KEY` | Yes (deploy) | Type **File** |
| `CI_REGISTRY_IMAGE` | Recommended | `registry.itnet-technologies.fr/segmentationvictory/frontend-jarvis` |
| `DAST_TARGET_URL` | Optional | Defaults to production HTTPS URL |
| `VITE_API_BASE_URL` | Optional | Usually leave empty |

Enable the Mac GitLab runner on **this** project (Settings → CI/CD → Runners) and ensure Wayhost security group allows **TCP 22** from the internet for deploy jobs.

---

## 12. 3D scene & assets

- Scene code: `src/scene/agents-scene.js`, `src/scene/navmesh.js`
- Progress bridge: `src/lib/agent-progress.js`
- Heavy assets live under `public/assets/` (models, Draco wasm) and are copied into `dist/` as-is
- Draco files are large; keep them out of unnecessary lint/scan paths where possible

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| API calls fail on `:5173` | Backend down / wrong proxy | Start backend; check `VITE_API_PROXY_TARGET` |
| Empty preview iframe | `site_url` points at backend localhost | Use `previewUrl()`; set backend `PUBLIC_BASE_URL` in prod |
| Deploy job: `WAYHOST_HOST` | Missing CI variable | Add it in GitLab CI/CD variables |
| Deploy job: SSH timeout | Security group blocks 22 | Open TCP 22 (and 80/443) on Wayhost SG |
| `web` image not found | Tag never pushed | Build/push `FRONTEND_TAG` to the registry |
| 404 on `/editeur` | Old static sync without nginx try_files | Use current nginx image / `nginx.conf` |

---

## 14. Related projects

| Repo | Role |
| --- | --- |
| [backend-jarvis](https://gitlab.itnet-technologies.fr/segmentationvictory/backend-jarvis) | API, agents, Postgres, sites, Compose/Caddy |
| n8n (Caleb) | Orchestration calling `/api/agents/*` |

---

## License / school context

Built for the ITNET **Segmentation Victory** project (prototype + DevSecOps qualification). Internal GitLab: `segmentationvictory/Frontend-Jarvis`.
