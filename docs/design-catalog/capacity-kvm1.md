# Capacity & runtime — Wayhost KVM1 (pinned)

## Inventory (confirmed)

| Spec | Value |
|------|-------|
| Plan | Wayhost **KVM1** (actif → 3 sept. 2026) |
| OS | Ubuntu |
| vCPU | **1** |
| RAM | **4 GB** |
| Disk | **50 GB** |

## Decision: Docker Compose — not k3s

| Option | Fit on KVM1 | Why |
|--------|-------------|-----|
| **Docker Compose + Caddy/nginx** | **Chosen** | ~200–350 MB platform overhead; rest for the app |
| k3s (single node) | **Rejected** | Official server baseline **2 CPU / 2 GB**; profiling ~**1.5 GB** for server+workload plumbing — leaves too little on **1 vCPU / 4 GB**, and canary/mesh adds more |

k3s is deferred until ≥ **2 vCPU / 8 GB** (e.g. KVM2+).

## ADR-005 status: Accepted

**Consequence:** progressive delivery via Compose + reverse-proxy, not Kubernetes Rollouts.

---

## Memory budget (hard ceiling)

Target: keep **≥400 MB free** under load to avoid OOM/swap thrash.

| Component | RAM limit | Notes |
|-----------|-----------|-------|
| Ubuntu + SSH + journald | ~400–600 MB | Keep lean; no desktop, no snap bloat |
| Docker Engine | ~150–250 MB | Install docker CE only; no Desktop |
| Edge (Caddy preferred) | 32–64 MB | TLS + HSTS; lighter than full Traefik+plugins |
| App (prod) | **512–1536 MB** | `mem_limit` in compose; size to actual language |
| Optional canary (short window) | **256–512 MB** | Only during promote; then remove |
| Metrics | **0–64 MB** | Wayhost panel + optional `node_exporter` only |
| **Reserve / page cache** | **≥400 MB** | Do not allocate |

**Never on this VPS:** GitLab Runner, Trivy/ZAP/Semgrep, DefectDojo, Prometheus+Grafana+Loki stack, Vault, k3s, second full app replica 24/7.

All scans stay on **GitLab shared runners**. DefectDojo = remote/group or skip for hackathon.

## Disk budget (50 GB)

| Use | Cap |
|-----|-----|
| OS + Docker | ~8–12 GB |
| Images (keep last **2** digests) | ≤8 GB — cron `docker image prune` |
| App volumes / logs | ≤5 GB — logrotate, `max-size`/`max-file` |
| Free | ≥15 GB always |

Build **never** on the VPS — only `docker pull` of `:sha` from GitLab Registry.

## Deploy strategies (KVM1-optimized)

| Strategy | On this box | Rule |
|----------|-------------|------|
| **Rolling (default)** | Yes | Stop old → start new **or** recreate one container; healthcheck then traffic. Lowest RAM. |
| **Blue-green** | Yes, **sequential** | Start blue → health OK → flip proxy → **stop green immediately**. Never run two full-size apps long. |
| **Canary** | Optional, short | Tiny canary (`mem_limit: 256m`) at 5–10% for 2–5 min; promote or kill. Skip multi-step 2→25→50→100 if RAM tight. |

Prefer **rolling + instant rollback to previous digest** for day-to-day speed on 1 vCPU.

## Compose template (resource-aware)

```yaml
services:
  edge:
    image: caddy:2-alpine
    mem_limit: 64m
    cpus: "0.20"
    ports: ["80:80", "443:443"]
    restart: unless-stopped

  app:
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
    mem_limit: 1280m
    cpus: "0.70"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/healthz"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

## Host hardening for speed

1. **Swap:** 1 GB file as OOM safety net only (`vm.swappiness=10`) — do not size to rely on swap.
2. **sysctl:** `vm.overcommit_memory=1` careful; prefer hard `mem_limit` so Docker OOMs the app, not the kernel.
3. **UFW:** 22 (runner IPs), 80, 443 only.
4. **unattended-upgrades** + reboot off-hours.
5. **Deploy job:** `docker compose pull && docker compose up -d --remove-orphans && docker image prune -f`.
6. **Static AI sites:** push to **Hosting Cloud** when possible — frees almost all VPS RAM for the API/generator.

## Performance checklist

- [ ] Distroless/alpine app images; multi-stage builds on CI  
- [ ] One process per container; no debug sidecars in prod  
- [ ] Health endpoints cheap (no DB hit every 2s if avoidable)  
- [ ] Gzip/brotli at Caddy; cache static assets  
- [ ] Connection limits tuned so 1 CPU isn’t event-loop starved  
- [ ] No cron storms; backups to Stockage Cloud off-peak  

## When to upgrade Wayhost plan

Move to **KVM2+** (or 2 vCPU / 8 GB) before considering k3s, dual always-on replicas, or full observability stack on-box.
