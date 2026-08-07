# Déploiement sur le VPS (Wayhost KVM1)

Cible : un VPS 4 Go. Cinq conteneurs — `edge` (Caddy), `web` (front nginx), `app`
(API), `worker` (file de travaux), `db` (PostgreSQL 16).

Deux dossiers sur la machine, et la distinction compte :

| Chemin | Contenu | Survit à un déploiement |
|---|---|---|
| `/opt/src/agentsea` | Les sources synchronisées, uniquement pour construire l'image | Non, écrasé à chaque fois |
| `/opt/app` | `docker-compose.yml`, `.env`, `Caddyfile`, `data/`, `sites/` | **Oui** — ce sont les données des clients |

---

## Première installation

```bash
# 1. Synchroniser le monorepo (racine complète : l'image a besoin de packages/)
rsync -a --delete --exclude '.git/' --exclude '**/.venv/' --exclude '**/node_modules/' \
      ./ vps:/opt/src/agentsea/

# 2. Poser les fichiers de déploiement
scp infra/kvm1/{docker-compose.yml,deploy.sh,Caddyfile,Caddyfile.http-dev,.env.example} \
    vps:/opt/app/

# 3. Sur le VPS
cd /opt/app
cp .env.example .env
```

Puis renseigner `.env`. Les entrées marquées **CRITIQUE** y sont commentées une par
une : `settings.validate()` refuse de démarrer en production si l'une d'elles est
absente ou dangereuse. Au minimum :

```bash
openssl rand -hex 32      # JWT_SECRET
openssl rand -base64 32   # INTERNAL_API_KEY, à reporter dans les workflows n8n
openssl rand -hex 16      # ANALYTICS_IP_SALT, propre à cette installation
```

`ADMIN_EMAILS` doit être renseigné **avant la première inscription** : sur une base
neuve, personne n'a de rôle et le back-office reste fermé à tout le monde.

### Tant qu'il n'y a pas de domaine

```bash
cp Caddyfile.http-dev Caddyfile     # écoute :80, pas d'ACME
```

et dans `.env` : `DOMAIN=:80`, `APP_ENV=development`. Garder `APP_ENV=production` avec
un `PUBLIC_BASE_URL` en HTTP ferait — volontairement — échouer le démarrage.

Une fois le DNS en place : restaurer `Caddyfile` (ACME), passer `DOMAIN` au domaine
réel, `PUBLIC_BASE_URL`/`APP_BASE_URL` en `https://`, `CORS_ORIGINS` sur l'origine
réelle, et `APP_ENV=production`.

---

## Déployer

```bash
cd /opt/app
APP_TAG=$(git -C /opt/src/agentsea rev-parse --short HEAD) ./deploy.sh
```

Le script, dans l'ordre : aligne la propriété de `data/` et `sites/` sur l'uid 10001
(sans quoi la première génération échoue en `PermissionError` avec un symptôme
trompeur), construit l'image depuis la racine du monorepo, recrée la pile, attend que
`app` réponde à `/healthz`, puis vérifie que `worker` tourne.

Ce dernier contrôle n'est pas du zèle. En `JOB_MODE=queue` sans worker, l'API accepte
les demandes de génération, les empile dans la table `jobs` et **reste parfaitement
verte** ; seules les sessions des clients restent « en cours » indéfiniment. C'est une
panne qui ne se voit d'aucun tableau de bord serveur.

### Vérifier

```bash
curl -fsS http://127.0.0.1/healthz          # vivacité de l'API
curl -fsS http://127.0.0.1/readyz           # + la base répond
docker compose logs -f worker               # « Worker … démarré »
docker compose ps
```

L'écran **Système** du back-office rejoue les contrôles de configuration : une
configuration qui dérive s'y constate sans ouvrir les journaux.

---

## Points à connaître

- **Le front n'est pas construit par `deploy.sh`.** En `DEPLOY_MODE=local`, seule
  l'image de l'API est construite sur le VPS ; `web` est tirée de `FRONTEND_IMAGE`.
  Construire le front à la main : `docker build -t <image> apps/web`.
- **Redémarrage du worker.** `SIGTERM` lui fait cesser de piocher, mais les générations
  en cours vont à leur terme (`stop_grace_period: 200s`). Les couper gaspillerait des
  appels au modèle déjà facturés.
- **Monter en charge** = ajouter des workers (`docker compose up -d --scale worker=3`).
  La réservation par `SELECT … FOR UPDATE SKIP LOCKED` garantit qu'un travail n'est
  jamais pris deux fois. Rien d'autre à reconfigurer — mais surveiller la mémoire : un
  worker est dimensionné à 1 Go sur un VPS qui en a 4.
- **Rien n'est sauvegardé.** Ni `pg_dump` planifié, ni copie de `sites/`. À mettre en
  place avant les premiers clients payants.
