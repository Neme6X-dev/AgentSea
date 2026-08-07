# DevSecOps Design Catalog — ITNET / EPITNET

Navigable architecture for a **secure, centralized CI/CD platform** on **GitLab + Wayhost**, applying ITNET DevSecOps workshop controls, Harness progressive delivery patterns, and secure-pipeline practices.

**Cloud constraint:** Wayhost only ([wayhost.cloud](https://wayhost.cloud)) — no AWS / Azure / GCP.

| Artifact | Path |
|----------|------|
| Requirements | [requirements.md](./requirements.md) |
| Platform architecture | [platform-architecture.md](./platform-architecture.md) |
| ADRs | [adrs/ADR-001-to-004.md](./adrs/ADR-001-to-004.md) |
| Platform API | [api-platform.md](./api-platform.md) |
| KVM1 capacity | [capacity-kvm1.md](./capacity-kvm1.md) |
| **VPS setup guide** | [../../infra/kvm1/README.md](../../infra/kvm1/README.md) |

**Verdict:** Industrialize with shared `ci-templates`, five security gates that **block on critical**, immutable images in **GitLab Registry**, deploy to **Wayhost KVM1 via Docker Compose** (not k3s), and **rolling-first** releases with sequential blue-green when needed.

**Pinned VPS:** KVM1 — 1 vCPU / 4 GB / 50 GB Ubuntu. Capacity plan: [capacity-kvm1.md](./capacity-kvm1.md).

---

## Big picture (EventStorming)

```mermaid
flowchart TB
    classDef event fill:#ff9800,stroke:#e65100,color:#000
    classDef command fill:#2196f3,stroke:#0d47a1,color:#fff
    classDef actor fill:#ffeb3b,stroke:#f57f17,color:#000
    classDef system fill:#9c27b0,stroke:#4a148c,color:#fff
    classDef aggregate fill:#4caf50,stroke:#1b5e20,color:#fff
    classDef hotspot fill:#f44336,stroke:#b71c1c,color:#fff

    Dev[Developer]:::actor
    Sec[Security Champion]:::actor
    SRE[Platform SRE]:::actor
    User[End User]:::actor

    Push[Push / Open MR]:::command
    Gate[Evaluate Security Gates]:::command
    BuildImg[Build & Sign Image]:::command
    DeployCanary[Deploy Canary Slice]:::command
    Promote[Promote / Shift Traffic]:::command
    Rollback[Rollback Traffic]:::command
    Remediate[Remediate Finding]:::command

    CodeCommitted[Code Committed]:::event
    SecretsFound[Secrets Detected]:::event
    VulnCritical[Critical Vuln Found]:::event
    GatesPassed[All Gates Passed]:::event
    ImagePublished[Image Published]:::event
    CanaryLive[Canary Serving Cohort]:::event
    HealthDegraded[Health Degraded]:::event
    ReleaseStable[Release Stable 100%]:::event
    FindingTracked[Finding Tracked in DefectDojo]:::event

    Pipeline[GitLab CI + ci-templates]:::system
    Registry[GitLab Container Registry]:::system
    Deploy[Deploy SSH / compose]:::system
    Wayhost[Wayhost VPS / Hosting]:::system
    Dojo[DefectDojo]:::system
    Obs[Prometheus / Wayhost metrics]:::system
    Discord[Discord Webhooks]:::system

    Release[Release]:::aggregate
    Finding[SecurityFinding]:::aggregate
    Artifact[ContainerArtifact]:::aggregate

    Hot1["? Hosting Cloud vs VPS default"]:::hotspot
    Hot2["? Severity policy: block vs warn"]:::hotspot

    Dev --> Push --> CodeCommitted
    CodeCommitted --> Gate
    Gate --> Pipeline
    Pipeline --> SecretsFound
    Pipeline --> VulnCritical
    Pipeline --> GatesPassed
    SecretsFound --> Finding
    VulnCritical --> Finding
    Finding --> FindingTracked --> Dojo
    FindingTracked --> Discord
    FindingTracked --> Remediate --> Push
    GatesPassed --> BuildImg --> ImagePublished --> Artifact --> Registry
    ImagePublished --> DeployCanary --> Deploy --> Wayhost
    DeployCanary --> CanaryLive
    CanaryLive --> User
    CanaryLive --> Obs
    Obs --> HealthDegraded
    HealthDegraded --> Rollback --> Release
    CanaryLive --> Promote --> ReleaseStable --> Release
    Sec --> Gate
    SRE --> DeployCanary
    Release -.question.- Hot1
    Finding -.question.- Hot2
```

---

## Process: Secure pipeline gates

```mermaid
flowchart TD
    classDef event fill:#ff9800,stroke:#e65100,color:#000
    classDef command fill:#2196f3,stroke:#0d47a1,color:#fff
    classDef system fill:#9c27b0,stroke:#4a148c,color:#fff
    classDef aggregate fill:#4caf50,stroke:#1b5e20,color:#fff

    Start([Commit / MR]) --> S1[1. Code analysis]:::command
    S1 --> Secrets[Gitleaks / Secret Detection]:::system
    S1 --> SAST[Semgrep / SonarQube]:::system
    Secrets --> Decision{Critical finding?}
    SAST --> Decision

    Decision -->|Yes| Block1[Block pipeline]:::event
    Block1 --> Alert[Notify Discord + DefectDojo]:::event
    Alert --> Fix[Team remediates]:::command
    Fix --> Start

    Decision -->|No| S2[2. Dependency SCA]:::command
    S2 --> SCA[Trivy / Dependency-Check]:::system
    SCA --> Decision2{Critical CVE?}
    Decision2 -->|Yes| Block1
    Decision2 -->|No| S3[3. Container security]:::command

    S3 --> Build[Docker multi-stage build]:::command
    Build --> ImgScan[Trivy image + SBOM]:::system
    ImgScan --> Decision3{Critical CVE / policy fail?}
    Decision3 -->|Yes| Block1
    Decision3 -->|No| S4[4. Infrastructure verify]:::command

    S4 --> IaC[Checkov / tfsec + Kyverno]:::system
    IaC --> Decision4{Policy fail?}
    Decision4 -->|Yes| Block1
    Decision4 -->|No| S5[5. Secure deploy]:::command

    S5 --> GitOps[GitOps sync to env]:::system
    GitOps --> DAST[OWASP ZAP / Nuclei]:::system
    DAST --> Decision5{Critical DAST?}
    Decision5 -->|Yes| Rollback[Rollback + alert]:::event
    Decision5 -->|No| Pass[Deploy authorized]:::event
    Pass --> Evidence[Retain artifacts as proof]:::aggregate
```

---

## Process: Progressive delivery

```mermaid
flowchart TD
    Ready[Gates passed + image in GitLab Registry] --> Strategy{Risk vs RAM?}

    Strategy -->|Default on KVM1| Rolling[Rolling recreate one container]
    Strategy -->|Major cutover| BG[Sequential blue-green]
    Strategy -->|Optional short soak| Canary[Light canary ≤512MB]

    Rolling --> Pull[docker compose pull :sha]
    Pull --> Up[up -d app + healthcheck]
    Up -->|Fail| RB1[Redeploy previous digest]
    Up -->|Pass| Prune[docker image prune -f]
    Prune --> Done[Stable — single app in RAM]

    BG --> StartBlue[Start BLUE with mem_limit]
    StartBlue --> Health[Health OK?]
    Health -->|No| Abort[Stop BLUE keep GREEN]
    Health -->|Yes| Flip[Caddy flip upstream]
    Flip --> StopGreen[Stop GREEN immediately]
    StopGreen --> Done

    Canary --> Tiny[Start canary mem_limit 256-512m]
    Tiny --> Weight[Route 5-10% ≤5 min]
    Weight --> CV{Errors / latency OK?}
    CV -->|No| Kill[Kill canary keep stable]
    CV -->|Yes| Promote[Replace stable with canary image]
    Promote --> Done
    Kill --> Done
```

---

## Process: AI site generator (hackathon)

```mermaid
flowchart LR
    classDef event fill:#ff9800,stroke:#e65100,color:#000
    classDef command fill:#2196f3,stroke:#0d47a1,color:#fff
    classDef actor fill:#ffeb3b,stroke:#f57f17,color:#000
    classDef hotspot fill:#f44336,stroke:#b71c1c,color:#fff

    User[User describes site]:::actor --> Gen[AI generates site code]:::command
    Gen --> Distrust[Never trust by default]:::event
    Distrust --> Commit[Commit to repo / MR]:::command
    Commit --> Pipe[DevSecOps pipeline]:::command
    Pipe --> Build[Build hardened image]:::command
    Build --> Deploy[Deploy if gates green]:::command
    Deploy --> Headers[Enforce HTTPS / HSTS headers]:::command
    Headers --> Live[Site available + monitored]:::event
    Live -.question.- Hot["? Wayhost Hosting Cloud vs VPS+Docker"]:::hotspot
```

---

## Data model

```mermaid
erDiagram
    SERVICE ||--o{ PIPELINE_RUN : triggers
    SERVICE ||--o{ ARTIFACT : produces
    PIPELINE_RUN ||--o{ SECURITY_FINDING : yields
    PIPELINE_RUN ||--o{ SCAN_REPORT : retains
    ARTIFACT ||--o{ RELEASE : deploys
    RELEASE ||--o{ TRAFFIC_SLICE : exposes
    SECURITY_FINDING }o--|| DEFECTDOJO_PRODUCT : tracked_in
    SERVICE }o--|| CI_TEMPLATE_SET : includes
    RELEASE }o--|| ENVIRONMENT : targets

    SERVICE {
        string name
        string repo_url
        string docker_image_base
        string defectdojo_product_id
    }
    PIPELINE_RUN {
        string id
        string branch
        string commit_sha
        string status
        datetime started_at
    }
    SECURITY_FINDING {
        string id
        string control_type
        string severity
        string status
        boolean blocks_deploy
    }
    SCAN_REPORT {
        string id
        string tool
        string artifact_uri
        datetime retained_until
    }
    ARTIFACT {
        string digest
        string tag_sha
        string sbom_uri
        boolean signed
    }
    RELEASE {
        string id
        string strategy
        string version
        string health
    }
    TRAFFIC_SLICE {
        int percent
        string cohort
        string revision
    }
    ENVIRONMENT {
        string name
        string cluster
        string namespace
    }
    CI_TEMPLATE_SET {
        string ref
        string files
    }
    DEFECTDOJO_PRODUCT {
        string id
        string name
    }
```

---

## State: Pipeline run

```mermaid
stateDiagram-v2
    [*] --> Queued: MR/push
    Queued --> Analyzing: secrets+SAST+SCA
    Analyzing --> Blocked: critical finding
    Analyzing --> Building: gates soft-pass
    Building --> ScanningImage: image built
    ScanningImage --> Blocked: critical CVE/policy
    ScanningImage --> Deploying: image ok
    Deploying --> DastRunning: synced to env
    DastRunning --> Blocked: critical DAST
    DastRunning --> Succeeded: no critical
    Blocked --> Queued: remediation commit
    Succeeded --> [*]
```

---

## State: Release (canary)

```mermaid
stateDiagram-v2
    [*] --> Pending: GitOps desire new version
    Pending --> Canary2: weight 2%
    Canary2 --> Canary25: CV pass
    Canary2 --> RolledBack: CV fail / error budget
    Canary25 --> Canary50: CV pass
    Canary25 --> RolledBack: CV fail
    Canary50 --> Canary100: CV pass
    Canary50 --> RolledBack: CV fail
    Canary100 --> Stable: soak window ok
    Canary100 --> RolledBack: late regression
    RolledBack --> Stable: previous revision restored
    Stable --> [*]
```

---

## Sequence: Secure release

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant GL as GitLab
    participant Tpl as ci-templates
    participant Scan as Security scanners
    participant Dojo as DefectDojo
    participant Reg as GitLab Registry
    participant VPS as Wayhost VPS
    participant Edge as Traefik TLS
    participant Obs as Metrics / health
    participant Hook as Discord

    Dev->>GL: push feature/* / MR
    GL->>Tpl: include security/build/deploy jobs
    Tpl->>Scan: secrets, SAST, SCA
    alt Critical finding
        Scan-->>Dojo: import findings
        Scan-->>Hook: critical alert
        Scan-->>GL: fail job (block)
        Dev->>GL: fix + push
    else Clean
        Tpl->>Reg: build & push :sha + SBOM
        Tpl->>Scan: Trivy image + IaC/compose policy
        Scan-->>GL: pass
        GL->>VPS: SSH/API deploy pull :sha
        VPS->>Edge: update canary weight / blue-green
        Tpl->>Scan: DAST vs DAST_TARGET_URL (Wayhost)
        Scan-->>Dojo: DAST results
        Obs-->>VPS: continuous verification signals
        alt SLO breach during canary
            Obs-->>Edge: rollback weights to stable
            Edge-->>Hook: rollback alert
        else Healthy
            Edge->>Edge: promote to 100%
        end
    end
```

---

## Architect review summary

| Area | Assessment |
|------|------------|
| Pattern fit | Industrialized templates + shift-left gates match ITNET docs |
| Cloud fit | Wayhost VPS + Hosting Cloud only — no hyperscalers |
| Security | Secrets→SAST→SCA→image→compose policy→DAST + TLS/HSTS on Wayhost |
| Delivery risk | Rolling-first on KVM1; sequential BG; light canary only |
| Debt risk | Auto-DevOps in `backend-jarvis` → migrate to `ci-templates` |
| Evolution | k3s only after KVM2+/8GB; Cosign; platform API |

## Confirm before implementation

1. SSH deploy key + UFW allowlist for GitLab runners  
2. Hosting Cloud vs VPS for static AI sites  
3. Critical CVE severities that hard-block  
4. DefectDojo remote (not on KVM1)  

## Next steps

1. Scaffold `ci-templates` + replace Auto-DevOps in pilot repo  
2. Ansible baseline on KVM1: Docker, Caddy, UFW, swap=1G, prune cron  
3. Compose with `mem_limit` / healthcheck; deploy = pull `:sha` + rolling  
4. Discord alerts; keep scanners on GitLab runners only
