# Déploiement sur le VPS Wayhost — variables à configurer

Deux endroits distincts, à ne pas confondre :

- **GitLab → Settings → CI/CD → Variables** : ce dont le *pipeline* a besoin pour déployer.
- **`/opt/app/.env` sur le VPS** : ce dont l'*application* a besoin pour tourner. Ce
  fichier n'est jamais versionné ; le pipeline y écrit seulement `CI_REGISTRY_IMAGE`,
  `APP_TAG`, `APP_PORT`, `DOMAIN` et `PUBLIC_BASE_URL`.

---

## 1. Variables GitLab CI/CD

| Variable | Obligatoire | Rôle |
| --- | --- | --- |
| `WAYHOST_HOST` | **oui** | hôte SSH du VPS |
| `WAYHOST_SSH_PRIVATE_KEY` | **oui** | clé privée de déploiement (type *File* ou masquée) |
| `DOMAIN` | **oui** | domaine public, ex. `sites.exemple.fr`. **Le job échoue volontairement sans elle** : sans domaine, chaque site publié renverrait une URL inutilisable au client |
| `PUBLIC_BASE_URL` | non | déduite en `https://$DOMAIN` si absente |
| `CI_REGISTRY_*` | auto | fournies par GitLab |
| `DAST_TARGET_URL` | non | définit-la seulement si vous voulez lancer le scan DAST |

---

## 2. Fichier `/opt/app/.env` sur le VPS

### Indispensables — rien ne démarre sans elles

```dotenv
# Base de données : le service `db` du docker-compose. L'hôte est `db`, pas localhost.
POSTGRES_PASSWORD=<mot de passe long et aléatoire>
DATABASE_URL=postgresql://sites:<le même mot de passe>@db:5432/sites

# Clé Gemini — https://aistudio.google.com/apikey
GEMINI_API_KEY=<clé>

# Secrets applicatifs — à générer, JAMAIS de valeur devinable :
#   python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=<64 caractères hexadécimaux>
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
INTERNAL_API_KEY=<clé de service, à donner aussi à n8n>

# Port interne écouté par le conteneur, référencé par Caddy.
APP_PORT=8080

# Origine du front, pour le CORS. Sans elle le navigateur bloquera tous les appels.
CORS_ORIGINS=https://<domaine-du-front>
```

`DOMAIN` et `PUBLIC_BASE_URL` sont écrites automatiquement par le pipeline ; inutile de
les saisir à la main.

### Modèles Gemini

```dotenv
GEMINI_MOCK=false
GEMINI_CODER_MODEL=gemini-flash-latest
GEMINI_REVIEWER_MODEL=gemini-2.0-flash
GEMINI_TEMPERATURE=0.7
GEMINI_TIMEOUT_S=180
```

⚠️ **`gemini-2.5-flash` ne fonctionne pas** : Google le refuse aux comptes récents
(*« no longer available to new users »*). C'est un `404` sur le modèle, pas une erreur de
clé — ne cherchez pas du côté de l'authentification. Deux modèles **différents** pour le
codeur et la revue évitent qu'un agent note son propre travail.

### À laisser vides — important

```dotenv
VPS_HOST=
VPS_USER=
```

Le backend tourne **sur** le VPS et sert les sites depuis son propre volume. Renseigner
ces variables ferait basculer la publication vers un téléversement SFTP **vers une autre
machine**, alors que les fichiers sont déjà au bon endroit. Le nom des variables suggère
l'inverse : c'est le piège à éviter.

### Optionnelles

```dotenv
JWT_EXPIRE_MINUTES=120
AUTH_MAX_ATTEMPTS=10
AUTH_WINDOW_MINUTES=15
GOOGLE_CLIENT_ID=          # connexion Google
GOOGLE_CLIENT_SECRET=
GITHUB_CLIENT_ID=          # connexion GitHub
GITHUB_CLIENT_SECRET=
APP_MEM_LIMIT=1280m        # ajuster selon la RAM du VPS
CADDY_MEM_LIMIT=64m
DB_MEM_LIMIT=256m
```

---

## 3. Front-end

Au build (`npm run build`), Vite fige les variables dans le bundle :

```dotenv
VITE_API_BASE_URL=https://<domaine-du-backend>
```

Sans slash final. **Rien de secret ici** : tout ce qui est préfixé `VITE_` finit en clair
dans le JavaScript public. L'origine où le front est servi doit figurer dans le
`CORS_ORIGINS` du backend, sinon le navigateur bloquera chaque appel.

---

## 4. Première mise en ligne

```bash
cd /opt/app
mkdir -p data sites
sudo chown -R 10001:10001 data sites   # l'app tourne en uid 10001
# renseigner .env, puis depuis GitLab : lancer le job deploy_wayhost (manuel sur dev)
```

Vérifications, dans cet ordre :

```bash
docker compose ps                      # db healthy, app healthy, edge démarré
curl -fsS https://$DOMAIN/healthz      # {"status":"ok"}
docker compose logs app | tail -30     # migrations Alembic appliquées
```

Si l'app reste `unhealthy`, regardez les logs : le démarrage échoue **volontairement**
quand les migrations ne passent pas, plutôt que de créer un schéma que les révisions
suivantes ne sauraient plus faire évoluer.

Un site publié est ensuite servi à `https://$DOMAIN/sites/<slug>/live/`, directement par
Caddy depuis le volume — il reste donc en ligne même pendant un redéploiement du backend.
