# Requirements — ITNET DevSecOps Platform

**Sources:** Doc_Accompagnement_DevSecOps_ITNET (Bankole, août 2026), DevSecOps Approach deck, [Harness blue-green/canary](https://www.harness.io/blog/blue-green-canary-deployment-strategies), [Secure CI/CD pipeline](https://medium.com/@dave-patten/creating-a-secure-ci-cd-pipeline-8ec67f47e24d), repo `backend-jarvis` (GitLab Auto-DevOps baseline).

**Context:** Hackathon EPITNET theme — AI-assisted showcase-site generator with automated hosting — plus reusable platform for ITNET microservices.

## Business goals

| Goal | Success signal |
|------|----------------|
| Conciliate speed, quality, and security | Critical vulns block deploy; non-critical tracked |
| Detect early, fix fast, keep simple evidence | Scan reports as CI artifacts + DefectDojo |
| Industrialize security across services | Central `ci-templates`; per-service minimal `.gitlab-ci.yml` |
| Safe production releases | Canary (prod) / blue-green (cutover) with auto-rollback |

## Actors

| Actor | Role |
|-------|------|
| Developer | Commits code (incl. AI-generated); remediates findings |
| DevSecOps / Security champion | Owns templates, policies, severity gates |
| Platform / SRE | Owns Wayhost VPS/Hosting, Traefik, observability |
| On-call responder | Incidents, rollback, chaos drills |
| Auditor / lead | Reviews evidence (SBOM, scan reports, deploy audit) |
| End user | Consumes generated sites; traffic for canary cohorts |

## Functional requirements

1. **F1 — Secure SDLC gates:** secrets, SAST, SCA, container scan + SBOM, IaC policy, DAST — each commit/MR.
2. **F2 — Centralized pipelines:** shared GitLab templates; group vs project variables; branch rules (`dev`, `main`, `scan-*`).
3. **F3 — Artifact integrity:** immutable image tags (`:sha`), signed/provenance-ready path, no `:latest` in prod.
4. **F4 — Progressive delivery:** rolling (non-critical), blue-green (zero-downtime cutover), canary (prod progressive %).
5. **F5 — Runtime feedback:** continuous verification metrics drive promote/rollback; Discord/DefectDojo alerts.
6. **F6 — AI code distrust:** generated sites scanned before merge/host; security headers (HTTPS/HSTS) before public demo.

## Non-functional requirements

| NFR | Target (initial) |
|-----|------------------|
| Availability (prod sites) | 99.5% monthly (hackathon+) → 99.9% platform |
| Deploy frequency | Multiple/day on `dev`; gated on `main` |
| Change failure rate | < 15% with automated rollback |
| MTTR (security finding critical) | < 1 business day ownership + unblock path |
| Pipeline wall time | < 25 min full path (excl. long DAST soak) |
| Blast radius | Namespace + network policy isolation per service/env |
| Compliance evidence | Retained scan artifacts ≥ 90 days |

## Constraints

- **SCM/CI:** GitLab (`gitlab.itnet-technologies.fr`) — already using Auto-DevOps stages in this repo.
- **Cloud (mandatory):** **Wayhost only** ([wayhost.cloud](https://wayhost.cloud)) — ITNET sovereign cloud. **No AWS, Azure, or GCP.**
- **Wayhost products in scope:** VPS Cloud (KVM), Hosting Cloud, domaines, stockage cloud; dedicated later if needed.
- **Start small:** Gitleaks + Semgrep on one pilot before full gate severity.
- **Secrets:** Masked + Protected CI vars; inject at deploy to Wayhost env; optional Vault on VPS.
- **Windows:** Optional Wayhost Windows VPS only if required; default Linux + Docker.

## Out of scope (v1)

- Hyperscaler managed Kubernetes (AKS/EKS/GKE)
- Full multi-region active-active DR
- Replacing GitLab with Harness (patterns borrowed; tooling stays GitLab + deploy to Wayhost)

## Hotspots (need confirmation)

- ? Hosting Cloud vs VPS as default for AI-generated sites
- ? Wayhost deploy mechanism for CI (API, SFTP, SSH, panel token)
- ? DefectDojo on Wayhost VPS vs external
- ? Discord vs Teams as primary alert channel
- ? Terraform/API coverage for Wayhost provisioning
