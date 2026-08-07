# DefectDojo integration (remote findings hub)

DefectDojo aggregates Gitleaks, Semgrep, GitLab SAST/Secret Detection, and Checkov
reports from CI. It must **not** run on the Wayhost KVM1 (too heavy for 4 GB).

## Architecture

```text
GitLab runners (scans) → artifacts → defectdojo_import job → remote DefectDojo API
Wayhost KVM1            → app + Postgres + Caddy only
```

## 1. Run DefectDojo somewhere else

Pick one:

| Option | Where | Notes |
|--------|--------|------|
| A | Your Mac / spare laptop | Official [django-DefectDojo](https://github.com/DefectDojo/django-DefectDojo) `docker compose up` |
| B | Second Wayhost VPS (KVM2+) | Prefer ≥2 vCPU / 8 GB |
| C | ITNET shared DefectDojo | Ask admins for URL + API token |

Minimum local (Mac) quickstart:

```bash
git clone https://github.com/DefectDojo/django-DefectDojo.git
cd django-DefectDojo
./dc-build.sh   # or follow current upstream README
./dc-up.sh
# UI usually http://localhost:8080 — create admin, then API token
```

## 2. Create product + API token

1. Open DefectDojo UI → create product **backend-jarvis** (or any name).
2. Profile → API v2 Key → copy token.
3. Engagements can be auto-created by CI (`auto_create_context=true`).

## 3. GitLab CI/CD variables

Project → **Settings → CI/CD → Variables**:

| Variable | Example | Masked |
|----------|---------|--------|
| `DEFECTDOJO_URL` | `http://192.168.x.x:8080` | no |
| `DEFECTDOJO_API_TOKEN` | `…` | **yes** |
| `DEFECTDOJO_PRODUCT_NAME` | `backend-jarvis` | no |
| `DEFECTDOJO_ENGAGEMENT_NAME` | `ci-dev` (optional) | no |

If these are unset, the `defectdojo_import` job is **skipped** (pipeline stays green).

## 4. What CI uploads

| Report file | DefectDojo scan type |
|-------------|----------------------|
| `gitleaks-report.json` | Gitleaks Scan |
| `semgrep-report.json` | Semgrep JSON Report |
| `gl-secret-detection-report.json` | GitLab Secret Detection Report |
| `gl-sast-report.json` | GitLab SAST Report |
| `checkov-report.json` | Checkov Scan |

Script: [`infra/ci/defectdojo_import.sh`](../../infra/ci/defectdojo_import.sh)  
Job: `defectdojo_import` (stage `findings`)

## 5. Network note

The GitLab runner (Mac) must reach `DEFECTDOJO_URL`. If Dojo runs only on `localhost` on the same Mac as the runner, use `http://host.docker.internal:8080` or the Mac LAN IP from inside the job container.
