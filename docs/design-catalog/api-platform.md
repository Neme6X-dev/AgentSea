# Platform control-plane API (design)

Internal APIs for the DevSecOps platform — not the showcase-site product API. Style: REST, OpenAPI 3.1, RFC 7807 errors, bearer JWT or GitLab OIDC. Deploy targets are **Wayhost** hosts only.

## Resources

| Resource | Purpose |
|----------|---------|
| `/v1/services` | Registered microservices + DefectDojo product link |
| `/v1/pipeline-runs` | Recent CI runs / gate outcomes |
| `/v1/findings` | Aggregated security findings (proxy/cache of DefectDojo) |
| `/v1/releases` | Release + strategy + traffic percent |
| `/v1/artifacts` | Canary/blue-green promotion & rollback commands |

## Endpoint sketch

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v1/services` | cursor pagination |
| POST | `/v1/services` | register service (platform admin) |
| GET | `/v1/services/{id}/findings` | filter severity, status |
| GET | `/v1/releases?service_id=&env=` | list releases |
| POST | `/v1/releases/{id}/actions/promote` | advance canary step (RBAC) |
| POST | `/v1/releases/{id}/actions/rollback` | immediate rollback |
| GET | `/v1/pipeline-runs/{id}/reports` | links to retained artifacts |

## AuthZ

- `platform.admin` — register services, policy.
- `service.owner` — view findings, trigger rollback for own service.
- `auditor` — read-only evidence.

## Errors

`application/problem+json` with stable `type` URIs under `https://platform.itnet.example/errors/...`.

## Versioning

URI prefix `/v1`; deprecate with `Deprecation` + `Sunset` headers; no silent breaking changes.

## Note

v1 may be satisfied by GitLab + DefectDojo + Argo UIs only. Formal API is optional when industrializing beyond hackathon.
