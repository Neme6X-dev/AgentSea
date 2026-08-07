# Architecture du Backend — Générateur de sites vitrines

Document d'architecture du backend de la plateforme (repo Flo). Il décrit le rôle du
backend dans l'écosystème multi-agents, la stack technique, l'organisation du code,
le pipeline de génération, le modèle de données, l'API, la sécurité et le déploiement.

> Statut : documenté au 03/08/2026. L'authentification **GitHub OAuth** et la migration
> de la base de données **SQLite → PostgreSQL** sont **implémentées** (cf. sections 6
> et 8.3) et couvertes par des tests unitaires.

---

## 1. Vue d'ensemble

Le backend de Flo est le **cœur central** de la plateforme de génération de sites
vitrines : il est la source de vérité (utilisateurs, sessions, artefacts, sites) et
expose une API REST consommée par le front-end et par les workflows d'agents.

La plateforme est répartie entre plusieurs rôles :

| Rôle | Acteur | Périmètre |
| --- | --- | --- |
| **Backend + agents code/review** | Flo (ce repo) | API REST, persistance, génération, revue, déploiement, DevSecOps |
| **Agent designer + orchestration** | Caleb | Designer qui produit le `DesignSpec`, workflows **n8n** qui orchestrent les agents |
| **Infrastructure & config** | Emmy | VPS, nginx, n8n, `.env`, secrets |
| **Front-end** | repo séparé | Interface utilisateur (dashboard en français) |

Les workflows n8n de Caleb ne font **pas** la génération eux-mêmes : ils appellent le
backend de Flo via les endpoints `/api/agents/*`, qui exécutent les agents et
retournent les artefacts.

```
                        ┌───────────────────────────────┐
                        │        n8n (Caleb)            │
                        │  orchestrateur + designer     │
                        └──────────────┬────────────────┘
                                       │  POST /api/agents/* (JWT user
                                       │  ou INTERNAL_API_KEY)
                                       ▼
┌────────────┐   REST    ┌───────────────────────────────┐
│  Front-end │ ─────────▶│        Backend (Flo)          │
│ (séparé)   │           │  FastAPI + agents + DevSecOps │
└────────────┘           └──────────┬────────────────────┘
                                    │
                          ┌─────────┼──────────┐
                          ▼         ▼          ▼
                     SQLite/Postgres  sites/   Gemini API
                     (métadonnées)  (fichiers)  (LLM)
```

---

## 2. Stack technique

| Domaine | Choix | Justification |
| --- | --- | --- |
| Web framework | **FastAPI** | API REST typée, OpenAPI auto (`/docs`), async natif |
| Validation | **Pydantic V2** | Contrats partagés (source de vérité pour front et n8n) |
| Persistance | **PostgreSQL** via SQLAlchemy 2.0 (sync) + psycopg 3 + **Alembic** | Base de prod (cohérente avec n8n), pool de connexions, migrations versionnées |
| Migration | **Alembic** (`alembic upgrade head` au démarrage) | Source de vérité du schéma en prod |
| LLM | **Gemini** (`generativelanguage.googleapis.com`) | Client HTTP direct via `httpx`, mode mock déterministe |
| Mots de passe | **argon2** (`argon2-cffi`) | Hachage robuste par défaut |
| Jetons | **PyJWT** (HS256) | Sessions utilisateur |
| Google OAuth | `jwt.PyJWKClient` + certs Google | Vérification des `id_token` (RS256) |
| GitHub OAuth | `httpx` (échange de code côté serveur) | `POST /api/auth/github`, profils via l'API GitHub |
| VPS / SFTP | **paramiko** | Déploiement distant optionnel |
| HTTP | **httpx** | Client async pour Gemini |

---

## 3. Arborescence

```
app/
  __init__.py
  main.py              # Montage FastAPI, CORS, /sites statiques, lifespan (init DB)
  config.py            # Settings lus depuis .env (dataclass Settings + settings global)
  gemini.py            # Client Gemini (complete / complete_json) + mode mock
  db.py                # Persistance PostgreSQL (SQLAlchemy 2.0 sync + psycopg), CRUD stable
  contracts.py         # Schémas Pydantic partagés (API / agents / front)
  security.py          # argon2, JWT, Google/GitHub OAuth, rate-limit, dépendances d'auth
  services.py          # Étapes du pipeline (code → review → deploy) + vue de session
  deploy.py            # Écriture versionnée des sites, deploy local + VPS SFTP
  utils.py             # slugify / unique_slug
  agents/
    coder.py           # Agent codeur (Flo) : DesignSpec → site (html/css/js)
    reviewer.py        # Agent review (Flo) : SAST déterministe + revue LLM, fusion
    templates.py       # Catalogue de templates : repère de structure par secteur
    designer.py        # Choix du designer : n8n s'il répond, interne sinon
    designer_n8n.py    # Designer n8n (Caleb) via webhook : prompt → DesignSpec | None
    designer_mini.py   # Designer interne : prompt → DesignSpec (repli, et refontes)
  devsecops/
    sast.py            # Checks statiques déterministes (XSS, secrets, accessibilité…)
    report.py          # Rendu markdown d'un rapport de revue
  routers/
    auth.py            # /api/auth/* (register, login, google, github, me)
    sessions.py        # /api/sessions/* (création, listing, détail, édition IA)
    agents.py          # /api/agents/* (code, review) — appelés par n8n
    deploy.py          # /api/deploy — appelé par n8n
    dev.py             # /api/dev/generate — pipeline complet en 1 appel (plan B démo)
migrations/
  env.py               # Contexte Alembic (URL DB + métadonnées)
  versions/            # Revisions versionnées (schéma PostgreSQL)
tests/
  conftest.py          # Fixtures pytest : DB de test (Postgres), nettoyage par test
  test_db.py           # CRUD db.py contre Postgres (sessions, artefacts, slugs)
  test_agents.py       # Agents coder/reviewer/designer (Gemini mocké)
  test_services.py     # Pipeline code→review→deploy + vue de session
  test_sast.py         # Checks SAST déterministes
  test_security.py     # argon2, JWT, rate-limit, GitHub OAuth (httpx mocké)
  test_auth_router.py  # Endpoints /api/auth via TestClient
  test_sessions_router.py  # Endpoints /api/sessions via TestClient
  test_utils.py        # slugify / allocate_slug
data/
  (gitignoré)
sites/
  <slug>/v{n}/…        # Versions générées (index.html, style.css, script.js)
  <slug>/live/…        # Copie « live » de la dernière version (gitignoré)
```

---

## 4. Pipeline de génération

Un site est généré en trois étapes : **code → review → deploy**. Il existe trois
chemins d'exécution.

### 4.1 Étapes

1. **Code** (`run_code_step`) — l'agent codeur transforme un `DesignSpec` (et
   éventuellement une instruction d'édition + le site actuel) en un site statique
   (html/css/js). Le site est écrit versionné sur disque et un artefact `site` est
   ajouté. Numéro de version = max existant + 1.
2. **Review** (`run_review_step`) — l'agent review audite la version générée :
   checks SAST déterministes **+** analyse LLM, fusionnés en un `ReviewReport`
   (score/100, verdict `pass|warn|fail`, dimensions, findings).
3. **Deploy** (`run_deploy_step`) — copie la dernière version dans `sites/<slug>/live/`
   (déploiement local) ou téléverse sur le VPS (SFTP), puis marque la session
   `deployed` et stocke `site_url`.

Chaque étape écrit son état dans `sessions.steps` (historique visible dans la vue).

### 4.2 Chemins d'exécution

**A. Chemin du front — `POST /api/dev/generate`**
Un prompt déclenche toute la chaîne : crée la session → `designer.build_design_spec()`
→ code → review → deploy → retourne la `SessionView` complète.

Le designer est choisi à l'exécution : le webhook n8n est interrogé en premier, et toute
panne — injoignable, hors délai, réponse conversationnelle plutôt que DesignSpec —
retombe sur `designer_mini`. Le repli est silencieux pour l'utilisateur mais tracé dans
l'étape `design` de la session, afin qu'on sache toujours qui a produit le spec.

Une **refonte** ne passe jamais par n8n : le webhook ignore la session, et seul le
designer interne reçoit le spec actuel en contexte — c'est ce qui garantit que le nom et
les coordonnées du client survivent au changement de style.

**B. Mode orchestré (prod) — n8n (Caleb)**
L'ordre attendu est validé par la présence des artefacts :
1. `POST /api/agents/code` (avec le `DesignSpec` du designer n8n) → artefact `site`.
2. `POST /api/agents/review` → artefact `report`.
3. `POST /api/deploy` → session `deployed`.

**C. Édition IA — `POST /api/sessions/{id}/edit`**
Reprend la dernière version (`v{n}`), applique l'instruction via l'agent codeur avec
le site actuel en contexte, puis review et deploy → nouvelle version `v{n+1}`.

```
        ┌──────────────┐   DesignSpec    ┌──────────┐
 prompt │ designer     │ ───────────────▶│  codeur  │──▶ site v{n}
        │ (n8n|mini)   │                 └──────────┘     │
        └──────────────┘                                   ▼
                                                  ┌──────────┐
                          SessionView ◀────────── │ review   │──▶ report
                                                  └──────────┘     │
                                                                   ▼
                                                        ┌──────────┐
                                                        │  deploy  │──▶ live + site_url
                                                        └──────────┘
```

---

## 5. Composants détaillés

### 5.1 `config.py`
`Settings` (dataclass frozen) construit depuis l'environnement / `.env`. Points clés :
- `gemini_api_key`, `gemini_coder_model`, `gemini_reviewer_model`, `gemini_mock`.
- `jwt_secret`, `jwt_expire_minutes`, `internal_api_key`.
- `auth_max_attempts`, `auth_window_minutes` (rate-limit).
- `google_client_id`, `google_client_secret`.
- `vps_*` (`vps_configured` = host + user renseignés).
- `public_base_url`, `data_dir`, `sites_dir`.

### 5.2 `gemini.py`
- `GeminiClient.complete(system, user, json_mode)` → `POST generateContent`.
- `complete_json()` → parse JSON, tolérant aux fences markdown (`_extract_json`).
- `LLMError` → déclenche les retries des agents.
- **Mode mock** (`GEMINI_MOCK=true`) : `_mock_spec/site/report` déterministes, sans
  réseau. Utilisé pour tests, CI et plan B en démo.

### 5.3 `db.py` — persistance
Accès aux données via **SQLAlchemy 2.0 (sync) + psycopg 3**, signatures et retours
`dict` stables appelés par les routers/services (le changement de moteur SQLite→
Postgres n'a pas modifié les appels) :
- Users : `create_user`, `get_user`, `get_user_by_email`, `get_user_by_google_sub`,
  `get_user_by_github_id`, `link_google_sub`, `link_github_id`.
- Sessions : `create_session`, `allocate_slug` (slug unique global par boucle sur
  `get_session_by_slug`), `update_step` (historique JSON ; ne remplace pas un statut
  terminal `deployed`), `set_session_field`, `get_session`, `get_session_by_slug`,
  `list_sessions`.
- Artefacts : `add_artifact`, `get_artifacts`, `latest_version`.
- Moteur : `configure_engine(database_url)` force le driver `postgresql+psycopg`
  (psycopg 3) et le pool ; `_decode_json` désérialise les colonnes `steps`/`payload`.
- Schéma : **Alembic est la source de vérité** — `init_db()` exécute
  `run_migrations()` (`alembic upgrade head`), avec fallback `create_all` en cas
  d'échec (tests/bootstrap).

### 5.4 `security.py`
- **argon2** : `hash_password` / `verify_password`.
- **JWT HS256** : `create_access_token` (sub = user id, iat, exp), `decode_token`.
- **Google OAuth** : `verify_google_id_token` (JWKS, RS256, vérif `iss`/`aud`).
- **GitHub OAuth** : `exchange_github_code(code)` → access_token (échange **côté
  serveur**, jamais de secret dans le front), puis `get_github_user(token)` → profil
  (id, login, name, email). 401 si le code est invalide, 503 si GitHub non configuré.
- **Rate-limit** mémoire sur le login/register (`check_rate_limit`, `record_failure`,
  `reset_failures`).
- **Dépendances FastAPI** :
  - `current_user` (`CurrentUser`) — Bearer JWT utilisateur obligatoire.
  - `require_service_or_user` (`ServiceOrUser`) — JWT utilisateur **ou**
    `INTERNAL_API_KEY` (n8n) ; retourne le user si identifié, sinon `None`.

### 5.5 `contracts.py`
Schémas Pydantic V2 — **la référence du contrat** entre backend, n8n et front :
- Auth : `RegisterRequest`, `LoginRequest`, `GoogleAuthRequest`, `TokenResponse`,
  `UserPublic`.
- Design : `DesignSpec` (name, tagline, business_type, tone, style, language,
  `DesignPalette`, `DesignTypography`, `DesignSection[]`, `DesignContact`, cta).
- Site : `GeneratedSite` (html, css, js).
- Revue : `ReviewFinding`, `ReviewDimensions`, `ReviewReport` (score, verdict,
  findings, summary).
- Sessions : `CreateSessionRequest`, `EditSessionRequest`, `SessionStep`,
  `SessionView`, `SessionCreated`, `ArtifactRecord`.
- Agents (n8n) : `AgentCodeRequest/Response`, `AgentReviewRequest/Response`,
  `DeployRequest/Response`.

### 5.6 `services.py`
- Chargement : `load_site_version`, `get_latest_design_spec`.
- Étapes : `run_code_step`, `run_review_step`, `run_deploy_step`.
- Vue : `build_session_view(session)` → `SessionView` (versions `v1`, `v2`…, steps,
  dernier rapport).

### 5.7 `deploy.py`
- `write_site_files(slug, version, site)` → `sites/<slug>/v{n}/`.
- `deploy_local(slug)` → copie la dernière version dans `live/`, retourne l'URL
  `{public_base_url}/sites/<slug>/live/`.
- `deploy_vps(slug)` → SFTP (paramiko) vers le VPS, URL `https://<slug>.<domaine>/`
  (sous-domaine) ou `https://<host>/<slug>/`.

### 5.8 Agents
- **`coder.py`** — prompt système strict (HTML sémantique, responsive mobile-first,
  accessibilité, interdictions de sécurité : eval, innerHTML non échappé, handlers
  inline, scripts distants, liens http:// ; jamais d'infos de contact inventées ;
  langue = celle du spec). Sortie JSON `{html, css, js}` avec 2 retries et
  normalisation (`_normalize_site` : clés + limites de taille).
- **`reviewer.py`** — checks SAST (`_run_sast`) puis revue LLM ; fusion dédoublonnée
  des findings (SAST d'abord), dégradation des dimensions selon les findings,
  calcul `score`/`verdict`. Si Gemini est indisponible, le SAST suffit.
- **`designer_mini.py`** — designer interne : prompt brut → `DesignSpec` (2 retries,
  garantit une section `hero`). Sert de repli, et tient seul les refontes.
- **`designer_n8n.py`** — appelle le webhook de chat n8n et en extrait un `DesignSpec`.
  Tolérant sur la forme (objet direct, `{"output": …}`, liste d'items, JSON noyé dans de
  la prose), strict sur le fond : ne retourne que du `DesignSpec` validé, sinon `None`.
  **Ne lève jamais** — une orchestration externe absente ne doit pas faire échouer une
  génération.
- **`designer.py`** — façade qui tranche entre les deux et retourne `(spec, source)`,
  pour qu'un seul endroit décide et que l'interface puisse afficher qui a répondu.
- **`templates.py`** — catalogue de `app/templates/*.json` (secteur, style, pages,
  composants). `reference_block(spec)` donne au codeur un repère de structure adapté au
  métier, sans lui transmettre de HTML. Un secteur sans correspondance ne reçoit **rien**
  plutôt que la première fiche venue : une structure d'e-commerce pour une association
  orienterait le codeur à contresens. Ignoré en retouche, où le site actuel fait déjà
  référence.

### 5.9 DevSecOps
- **`sast.py`** — scans déterministes : JS (`eval`, `new Function`,
  `document.write`, innerHTML, handlers inline, `javascript:`), HTML (doctype,
  charset, viewport, lang, images sans alt, scripts/styles distants, liens http://,
  formulaires sans action), CSS (ressources distantes), secrets (clés API, clés
  privées, JWT). Chaque check → `ReviewFinding`.
- **`report.py`** — `render_markdown(report)` : rapport lisible (verdict, dimensions
  avec barres, findings détaillés).

### 5.10 Routers
| Fichier | Préfixe | Rôle |
| --- | --- | --- |
| `auth.py` | `/api/auth` | register, login, google, me |
| `sessions.py` | `/api/sessions` | création, listing, détail, artefacts, édition IA, retry |
| `agents.py` | `/api/agents` | code, review (appelés par n8n) |
| `deploy.py` | `/api` | deploy (appelé par n8n) |
| `dev.py` | `/api/dev` | generate (pipeline complet sans n8n) |

---

## 6. Modèle de données

```
users
  id            INTEGER PK (AUTOINCREMENT)
  email         TEXT UNIQUE NOT NULL
  password_hash TEXT            -- NULL pour les comptes OAuth
  google_sub    TEXT UNIQUE     -- id Google (OAuth)
  github_id     TEXT UNIQUE     -- id GitHub (OAuth)
  provider      TEXT 'local' | 'google' | 'github'
  name          TEXT
  created_at    TEXT (ISO UTC)

sessions
  id            TEXT PK (uuid hex, 12 chars)
  user_id       INTEGER FK → users(id) ON DELETE CASCADE
  slug          TEXT UNIQUE NOT NULL   -- slug lisible du site
  prompt        TEXT NOT NULL
  status        TEXT 'pending' | ... | 'deployed'
  current_step  TEXT
  steps         TEXT JSON []            -- historique {step, status, detail, ts}
  error         TEXT
  site_url      TEXT                    -- URL du live (après deploy)
  created_at    TEXT
  updated_at    TEXT

artifacts
  id            INTEGER PK (AUTOINCREMENT)
  session_id    TEXT FK → sessions(id) ON DELETE CASCADE
  kind          TEXT 'design_spec' | 'site' | 'report' | 'deploy'
  version       INTEGER (v1, v2, …)
  payload       TEXT JSON               -- contenu de l'artefact
  created_at    TEXT
```

Index : `idx_sessions_user (user_id)`, `idx_artifacts_session (session_id, kind)`.

Les **fichiers** des sites ne sont pas en base : ils vivent sur disque dans
`sites/<slug>/v{n}/` et `live/` ; la base référence les métadonnées (versions,
chemins, URL).

---

## 7. API

Documentation interactive : `/docs` (OpenAPI généré par FastAPI).

| Méthode | Chemin | Auth | Rôle |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | public | Inscription email/mot de passe → token |
| POST | `/api/auth/login` | public | Connexion (rate-limit) → token |
| POST | `/api/auth/google` | public | Connexion Google OAuth (id_token) |
| POST | `/api/auth/github` | public | Connexion GitHub OAuth (échange de code) |
| GET | `/api/auth/me` | JWT user | Profil courant |
| POST | `/api/sessions` | JWT user | Créer une session |
| GET | `/api/sessions` | JWT user | Lister ses sessions |
| GET | `/api/sessions/{id}` | JWT user | Détail (steps, versions, rapport) |
| GET | `/api/sessions/{id}/artifacts` | JWT user | Artefacts de la session |
| POST | `/api/sessions/{id}/edit` | JWT user | Édition IA → nouvelle version |
| POST | `/api/sessions/{id}/retry` | JWT user | Relancer une étape |
| POST | `/api/dev/generate` | JWT user | Pipeline complet en 1 appel (démo) |
| POST | `/api/agents/code` | JWT user ou INTERNAL_API_KEY | n8n → agent codeur |
| POST | `/api/agents/review` | JWT user ou INTERNAL_API_KEY | n8n → agent review |
| POST | `/api/deploy` | JWT user ou INTERNAL_API_KEY | n8n → déploiement |
| GET | `/sites/<slug>/live/` | public | Site vitrine généré (statique) |

**Sécurité des endpoints agents** : `ServiceOrUser` accepte un JWT utilisateur (auquel
cas l'accès à la session est restreint au propriétaire) **ou** la clé `INTERNAL_API_KEY`
(accès service, n8n).

---

## 8. Authentification

Trois méthodes d'authentification :

1. **Email + mot de passe** — hachage argon2, token JWT HS256. Rate-limit sur le
   login (10 tentatives / 15 min par email+IP, en mémoire).
2. **Google OAuth** — le front envoie un `id_token` Google ; le backend le vérifie
   (JWKS publics Google, RS256, `iss`/`aud`), crée l'utilisateur ou lie `google_sub`.
3. **GitHub OAuth** — flux d'échange de code côté serveur : le front redirige vers
   GitHub, obtient un code, et le backend échange le code contre un `access_token`
   (secret côté serveur, jamais exposé) via `POST https://github.com/login/oauth/
   access_token`, puis récupère l'utilisateur via `GET https://api.github.com/user`.
   L'utilisateur est stocké avec `users.github_id` (unique) ; si le compte existe déjà
   par email, le `github_id` est lié (provider → `github`). Settings : `GITHUB_CLIENT_ID`
   / `GITHUB_CLIENT_SECRET` (le flux est désactivé, 503, tant qu'ils sont absents).

---

## 9. Sécurité & DevSecOps

- **Mots de passe** : argon2 (jamais de stockage en clair).
- **JWT** : HS256, expiration configurable, `sub` = id utilisateur.
- **Isolation par utilisateur** : chaque route vérifie que la session appartient au
  user courant (403 sinon) ; les appels service (n8n) passent par `INTERNAL_API_KEY`.
- **Rate-limit** sur l'auth (mémoire).
- **Google OAuth** : vérification cryptographique des `id_token` (signature + issuer +
  audience), pas de confiance sur le payload envoyé par le client.
- **SAST** sur chaque site généré (étape review) : XSS (eval, innerHTML, handlers
  inline, `javascript:`), ressources/scripts distants, liens http://, secrets en dur
  (clés API, clés privées, JWT), accessibilité (lang, alt, viewport), responsive.
- **Agent codeur** : prompt système interdisant explicitement les pratiques dangereuses
  et l'invention de données de contact.
- **Retries** : agents avec 2 tentatives ; la review fonctionne même si Gemini est
  indisponible (rapport basé sur le SAST).

---

## 10. Déploiement

- **Local (défaut)** : les sites sont servis statiquement par le backend via
  `/sites` (`StaticFiles`), URL `{public_base_url}/sites/<slug>/live/`.
- **VPS (optionnel)** : si `VPS_HOST`/`VPS_USER` sont renseignés, `deploy_vps`
  téléverse `live/` en SFTP (paramiko). URL selon config : sous-domaine
  `https://<slug>.<domaine>/` ou chemin `https://<host>/<slug>/`.
- Les versions restent disponibles sous `sites/<slug>/v{n}/` (rollback possible via
  un re-déploiement).

---

## 11. Tests

Suite **pytest** par feature dans `tests/` (déterministe : Gemini en mock, Postgres de
test dédié, aucune requête réseau) :

| Fichier | Couvre |
| --- | --- |
| `test_db.py` | CRUD PostgreSQL (users, sessions, artefacts, `allocate_slug`, `update_step`) |
| `test_agents.py` | Agents coder/reviewer/designer : happy paths, retries, fallback LLM |
| `test_services.py` | Pipeline code→review→deploy (écriture fichiers, artefacts, statut `deployed`) |
| `test_sast.py` | Checks SAST : XSS, scripts/liens distants, secrets, accessibilité |
| `test_security.py` | argon2, JWT (expiration/token invalide), rate-limit, GitHub OAuth (httpx mocké) |
| `test_auth_router.py` | Endpoints `/api/auth/*` (register/login/google/github/me) via TestClient |
| `test_sessions_router.py` | Endpoints `/api/sessions/*` (création/list/détail/edit/retry) |
| `test_utils.py` | `slugify` / `allocate_slug` |

Lancer : `pytest tests -q` (nécessite un Postgres de test — cf. `TEST_DATABASE_URL` dans
`tests/conftest.py` ; en local, la base `sites_test` du Postgres portable de dev).

---

## 12. Décisions d'architecture (ADR courts)

1. **Backend central = source de vérité.** Users, sessions, artefacts et sites
   vivent chez Flo ; n8n et le front ne font que consommer l'API.
2. **n8n = fournisseur d'agents externe.** Les workflows appellent `/api/agents/*`
   avec `INTERNAL_API_KEY` ; le backend n'embarque pas n8n.
3. **Contrats Pydantic = référence unique.** `contracts.py` est consommé par le
   backend, documenté via `/docs` pour n8n (Caleb) et le front.
4. **Édition par nouvelle version.** Une instruction d'édition génère `v{n+1}` ;
   l'historique des versions est conservé.
5. **Sync pour la couche DB.** Les fonctions d'accès restent synchrones ; le pool de
   connexions (Postgres) gère la concurrence. Simplifie le code, suffisant pour la
   charge visée.
6. **PostgreSQL partout (dev + prod).** Migration SQLite → Postgres réalisée via
   SQLAlchemy 2.0 (sync) + psycopg 3, signatures `db.py` inchangées, schéma piloté par
   Alembic (`alembic upgrade head` au démarrage), `DATABASE_URL` dans `.env`.
7. **Déploiement statique.** Aucun framework côté site généré ; les fichiers sont
   écrits sur disque puis servis/copiés (autonomie totale, pas de build).
8. **SAST + LLM pour la revue.** Les checks déterministes garantissent un minimum de
   qualité/sécurité même si le LLM échoue ; l'LLM apporte la lecture de la fidélité
   design et des dimensions.
