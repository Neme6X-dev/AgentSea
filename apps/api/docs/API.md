# Contrat d'API — backend de génération de sites vitrines

Référence d'intégration pour **le front-end** et **les workflows n8n (Caleb)**.
Documentation interactive toujours à jour : `GET /docs` · schéma brut : `GET /openapi.json`.

- Base locale : `http://127.0.0.1:8000`
- Sondes : `GET /healthz` et `GET /api/health` → `{"status":"ok","service":"jarvis-api","version":"1.0.0"}`

---

## 1. Authentification

Deux identités coexistent, toutes deux en en-tête `Authorization: Bearer <jeton>` :

| Appelant | Jeton | Portée |
| --- | --- | --- |
| **Front-end** (utilisateur) | JWT rendu par `/api/auth/*` | ne voit que ses propres sessions |
| **n8n** (service) | valeur de `INTERNAL_API_KEY` | `/api/agents/*` et `/api/deploy` uniquement |

> La clé de service passe bien dans `Authorization: Bearer`, **pas** dans un en-tête
> `X-Internal-Key`. Un appel service n'est rattaché à aucun utilisateur : il n'y a donc
> pas de contrôle de propriété sur la session, la clé doit rester secrète.

### Obtenir un JWT

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@flo.fr","password":"MotDePasse123!","name":"Démo"}'
```

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user": {"id": 1, "email": "demo@flo.fr", "name": "Démo", "provider": "local"}
}
```

| Endpoint | Corps | Notes |
| --- | --- | --- |
| `POST /api/auth/register` | `{email, password, name?}` | 201 · mot de passe ≥ 8 caractères · 409 si l'email existe |
| `POST /api/auth/login` | `{email, password}` | 401 si invalide · limité en tentatives |
| `POST /api/auth/google` | `{id_token}` | jeton Google Identity |
| `POST /api/auth/github` | `{code}` | code OAuth, échangé côté serveur |
| `GET /api/auth/me` | — | profil courant |

---

## 2. Parcours front-end

### 2.1 Créer une session

```bash
curl -X POST http://127.0.0.1:8000/api/sessions \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"prompt":"Restaurant africain Chez Amara à Lyon, ambiance chaleureuse"}'
```
→ `201 {"id":"a1b2c3d4","slug":"chez-amara","status":"pending"}`

### 2.2 Suivre une session

`GET /api/sessions` (liste) et `GET /api/sessions/{id}` (détail) renvoient une **SessionView** :

```json
{
  "id": "a1b2c3d4",
  "slug": "chez-amara",
  "prompt": "Restaurant africain…",
  "status": "deployed",
  "current_step": "deploy",
  "steps": [{"step": "code", "status": "done", "detail": "Version v1 générée", "ts": "…"}],
  "versions": ["v1", "v2"],
  "site_url": "http://127.0.0.1:8000/sites/chez-amara/live/",
  "published_version": 1,
  "previews": [
    {"version": 1, "url": "http://127.0.0.1:8000/sites/chez-amara/v1/", "score": 92, "verdict": "pass", "published": true},
    {"version": 2, "url": "http://127.0.0.1:8000/sites/chez-amara/v2/", "score": 78, "verdict": "warn", "published": false}
  ],
  "report": { "score": 78, "verdict": "warn", "dimensions": {…}, "findings": […], "summary": "…" },
  "error": null,
  "created_at": "…", "updated_at": "…"
}
```

Points d'attention côté affichage :

- `site_url` = ce que voient les visiteurs. `previews[].url` = chaque version, consultable
  sans être publiée. `published: true` marque celle qui est en ligne.
- `report.llm_available: false` signale une **revue partielle** (modèle indisponible) :
  affichez-le comme tel plutôt que comme un mauvais score.
- `report.findings[].source` vaut `sast` (contrôle déterministe) ou `llm` (analyse du modèle).

### 2.3 Modifier, prévisualiser, publier

```bash
# 1. Modifier → produit une nouvelle version
curl -X POST http://127.0.0.1:8000/api/sessions/$ID/edit \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"instruction":"Ajoute une section Horaires"}'

# 2. Publier la version choisie (omettre "version" = la dernière)
curl -X POST http://127.0.0.1:8000/api/sessions/$ID/publish \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"version": 2}'
```

**Retouche ou refonte** — `/edit` accepte deux intentions, qui n'ont pas le même point de
départ. Le champ `mode` vaut `tweak` par défaut.

| Intention | Payload | Comportement |
| --- | --- | --- |
| **Retouche** | `{"instruction": "…"}` | le design actuel est conservé et le site existant transmis au codeur, qui doit le préserver |
| **Refonte** | `{"instruction": "…", "design_spec": { … }}` | le nouveau spec fait foi, le site actuel **n'est pas** transmis |
| **Refonte sans spec** | `{"instruction": "…", "mode": "redesign"}` | le backend régénère lui-même un spec depuis l'instruction, en conservant nom et contacts |

Fournir un `design_spec` vaut refonte, quel que soit le `mode` annoncé : c'est le designer
n8n qui a tranché. La distinction compte, car en refonte transmettre le site actuel pousse
le modèle à recopier le design qu'on cherche justement à remplacer — et le site produit est
validé contre le **nouveau** spec, pas l'ancien.

```bash
# Refonte pilotée par le designer n8n
curl -X POST http://127.0.0.1:8000/api/sessions/$ID/edit \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"instruction":"Ambiance sombre et éditoriale","design_spec":{ … }}'
```

`/edit` répond **`202 Accepted`** et travaille en tâche de fond, comme
`/api/dev/generate` : le front suit `GET /api/sessions/{id}` jusqu'à un statut terminal
(`deployed`, `ready` ou `error`). Une édition qui s'arrête en prévisualisation passe en
`ready` — sans ce statut, le front interrogerait sans fin une session pourtant finie.

**Règle de publication** — elle conditionne tout l'écran d'édition du front :

| Situation | Comportement de `/edit` |
| --- | --- |
| Le site n'a jamais été publié | la nouvelle version part **directement en ligne** |
| Le site est déjà publié | l'édition **s'arrête en prévisualisation** ; `live/` ne bouge pas tant que `/publish` n'est pas appelé |

`POST /api/sessions/{id}/publish` — corps `{"version": int|null, "force": bool}` :

- `version: null` → publie la dernière version générée ;
- **publier une version antérieure est le retour arrière** : toutes les versions restent sur disque ;
- `404` si la version n'existe pas pour cette session ;
- `409` si la version visée a le verdict `fail` — le corps précise pourquoi :

```json
{"detail": {
  "message": "La v2 a le verdict « fail » (score 30/100).",
  "score": 30,
  "blocking_findings": ["eval() détecté"],
  "hint": "Relancez avec force=true pour publier malgré tout."
}}
```

Le front doit alors proposer un choix explicite, et renvoyer `{"version":2,"force":true}` si
l'utilisateur confirme.

### 2.4 Autres

| Endpoint | Rôle |
| --- | --- |
| `GET /api/sessions/{id}/artifacts` | historique brut (design_spec, site, report, deploy) |
| `POST /api/sessions/{id}/retry` | relance la dernière étape en échec |
| `POST /api/dev/generate` | lance le pipeline complet **en tâche de fond** (202) |

### 2.5 Génération asynchrone — `POST /api/dev/generate`

**`202 Accepted`** : la main est rendue dès la session ouverte, le pipeline
(design → code → review → deploy) se poursuit côté serveur.

```bash
curl -X POST http://127.0.0.1:8000/api/dev/generate \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"prompt":"Restaurant africain à Lyon","design_spec":{ … }}'
# → 202 {"id":"a1b2c3d4","slug":"chez-amara","status":"running","steps":[…]}
```

Le front suit ensuite `GET /api/sessions/{id}` jusqu'à un statut terminal —
`deployed` ou `error`. C'est ce qui rend l'avancement observable : un appel synchrone
ne rendrait la main qu'à la fin, et il n'y aurait rien à afficher pendant la minute de
génération. Les `steps` alimentent la scène 3D des agents (`src/lib/agent-progress.js`
côté front fait la correspondance étape → agent).

Un échec en tâche de fond n'a personne pour le recevoir : il est consigné sur la
session (`status: "error"`, champ `error`), jamais seulement dans les logs.

`design_spec` est optionnel — fourni, il court-circuite l'étape de design (cf. §2.6).

### 2.6 Cadrage conversationnel — `POST /api/chat`

Relais vers l'agent conversationnel n8n. Le front passe par le backend plutôt que
d'appeler le webhook directement : pas de préflight CORS vers un domaine tiers, et
l'URL n8n se change côté serveur sans reconstruire le bundle.

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"message":"Je veux un site pour mon restaurant"}'
```
```json
{
  "conversation_id": "9f2c…",
  "reply": "Quel est votre secteur d'activité et quel type de site avez-vous en tête ?",
  "design_spec": null,
  "available": true
}
```

| Champ | Rôle |
| --- | --- |
| `conversation_id` | fil côté n8n — **à renvoyer à chaque tour**, sinon l'agent repose les mêmes questions |
| `design_spec` | `null` tant que l'agent cadre encore ; rempli quand le besoin est cerné |
| `available` | `false` si n8n n'a pas répondu ; `reply` porte alors un message explicatif |

**`design_spec` est le signal de génération.** Tant qu'il est nul, il n'y a rien à
générer : c'est précisément ce qui empêche un « bonjour » de produire un site que
personne n'a demandé. Une panne n8n ne renvoie pas d'erreur HTTP — le front doit
pouvoir proposer de continuer sans cadrage plutôt que de laisser l'utilisateur devant
un échec dont il ne peut rien faire.

Le spec obtenu se passe ensuite à `POST /api/dev/generate` dans `design_spec` : le
cadrage fait alors foi et l'étape de design est court-circuitée, sans quoi on
générerait un autre site que celui qui vient d'être validé avec l'utilisateur.

### 2.7 Designer n8n en amont de `/api/dev/generate`

Ce chemin est celui du front : un seul prompt déclenche toute la chaîne. Le designer
est choisi à l'exécution, et l'étape `design` de la `SessionView` dit lequel a répondu :

| `steps[].detail` | Sens |
| --- | --- |
| `Spécification issue du cadrage avec l'agent conversationnel` | `design_spec` fourni par le front (cf. §2.5) |
| `Spécification produite par le designer n8n` | le webhook a rendu un DesignSpec conforme |
| `… par le designer interne (n8n indisponible)` | repli : webhook muet, hors délai, ou réponse hors contrat |

Le repli n'est pas une erreur et ne se voit pas dans le résultat : la génération continue
normalement. Configuration dans `.env` — `N8N_DESIGNER_URL` (vide = designer interne
seul, aucun appel réseau) et `N8N_TIMEOUT_S`.

**Ce que le webhook doit renvoyer** pour être retenu : un DesignSpec JSON, accepté sous
l'une de ces formes — objet direct, `{"output": "<json>"}`, ou liste d'items n8n. Le JSON
est extrait même s'il est entouré de prose. Une réponse purement conversationnelle
(« Quel est votre secteur ? ») n'est pas exploitable et déclenche le repli.

---

## 3. Parcours n8n (Caleb)

Trois appels, dans cet ordre. L'ordre est vérifié par la présence des artefacts : un
`review` sans `code` renvoie 400.

```bash
AUTH="Authorization: Bearer $INTERNAL_API_KEY"

# 1. Génération du code à partir du DesignSpec produit par le designer
curl -X POST http://127.0.0.1:8000/api/agents/code -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"session_id":"a1b2c3d4","design_spec":{ … }}'
# → 201 {"slug":"chez-amara","version":1,"files":{"index.html":"sites/chez-amara/v1/index.html","version":"1"}}

# 2. Revue qualité + sécurité
curl -X POST http://127.0.0.1:8000/api/agents/review -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"session_id":"a1b2c3d4","slug":"chez-amara"}'
# → 200 {"slug":"chez-amara","report":{"score":92,"verdict":"pass","dimensions":{…},"findings":[…]}}

# 3. Mise en ligne
curl -X POST http://127.0.0.1:8000/api/deploy -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"session_id":"a1b2c3d4","slug":"chez-amara"}'
# → 200 {"slug":"chez-amara","version":1,"target":"local","url":"http://127.0.0.1:8000/sites/chez-amara/live/"}
```

La session doit exister au préalable (`POST /api/sessions`, appel utilisateur).
`POST /api/agents/code` accepte aussi `instruction` (string) pour une édition.

### DesignSpec — contrat d'entrée du codeur

Seul `name` est obligatoire ; tout le reste a une valeur par défaut. Ce que le designer
remplit conditionne directement la qualité du site.

```json
{
  "name": "Chez Amara",
  "tagline": "Cuisine ouest-africaine, recettes de famille",
  "business_type": "restaurant",
  "description": "Restaurant familial installé à Lyon depuis 2015.",
  "tone": "chaleureux",
  "audience": "familles et groupes d'amis du quartier",
  "style": "moderne",
  "language": "fr",
  "palette": {"primary": "#b23a17", "secondary": "#f7ede2", "accent": "#e8a33d", "bg": "#fffaf5", "text": "#2b1a12"},
  "typography": {"heading_font": "Georgia, serif", "body_font": "system-ui, sans-serif", "base_size": "17px"},
  "sections": [
    {"id": "hero", "title": "Accueil", "content": "…", "order": 0},
    {"id": "apropos", "title": "À propos", "content": "…", "order": 1}
  ],
  "contact": {"phone": "", "email": "", "address": "", "hours": ""},
  "cta": "Réserver une table"
}
```

- `style` est contraint : `minimal | moderne | premium | playful | editorial`.
- **`contact` vide reste vide.** Le backend vérifie qu'aucun téléphone ni email n'apparaît
  dans un site dont le spec n'en fournit pas : un faux numéro sur un site en production
  envoie les prospects du client chez quelqu'un d'autre. Ne remplissez ces champs que si
  l'utilisateur les a réellement donnés.
- Chaque `sections[].id` doit se retrouver comme `<section id="…">` dans le site ; c'est
  vérifié côté backend.

---

## 4. Codes d'erreur

| Code | Sens | Réaction attendue |
| --- | --- | --- |
| `400` | étape hors séquence (review avant code), session sans design_spec | corriger l'ordre du workflow |
| `401` | jeton absent ou invalide | ré-authentifier |
| `403` | la session appartient à un autre utilisateur | ne pas réessayer |
| `404` | session ou version inconnue | ne pas réessayer |
| `409` | email déjà pris, ou publication d'une version `fail` | demander confirmation à l'utilisateur |
| `422` | corps non conforme au schéma | corriger le payload |
| **`502`** | **le fournisseur LLM est indisponible** — le corps porte `"retryable": true` | **réessayer avec un délai** (n8n : nœud *Retry On Fail*) |
| `500` | bug côté backend | remonter le log |

Le `502` est le seul cas où un nouvel essai a un sens. La génération réessaie déjà trois
fois en interne avec une pause croissante ; un `502` signifie que ces trois essais ont
échoué.

---

## 5. Sites générés

| Chemin | Contenu |
| --- | --- |
| `/sites/<slug>/v{n}/index.html` | une version précise — **prévisualisation** |
| `/sites/<slug>/live/index.html` | la version publiée — **ce que voient les visiteurs** |

Chaque version contient `index.html`, `style.css`, `script.js`, sans dépendance externe :
les sites fonctionnent hors ligne sur n'importe quel serveur statique.
