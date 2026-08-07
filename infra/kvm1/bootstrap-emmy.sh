#!/usr/bin/env bash
# Amorçage manuel du VPS Wayhost, sous l'utilisateur emmy (pas de compte de déploiement
# dédié). À lancer depuis un poste de développement :
#
#   ADMIN_EMAILS=vous@exemple.tld bash infra/kvm1/bootstrap-emmy.sh
#
# À n'exécuter qu'une fois, sur une machine vierge : le script **écrase** /opt/app/.env.
# Pour les déploiements suivants, utiliser infra/kvm1/deploy.sh (cf. README.md).
set -euo pipefail

# Racine du monorepo. C'est elle qui est synchronisée : l'image de l'API embarque
# `packages/templates/catalog`, qui vit en dehors de `apps/api/`.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KEY="${WAYHOST_SSH_KEY:-$HOME/.ssh/wayhost_deploy}"
HOST="${WAYHOST_HOST:-45.93.21.45}"
REMOTE="emmy@${HOST}"
SRC_DIR="${SRC_DIR:-/opt/src/agentsea}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=yes -o ConnectTimeout=20)
RSYNC_SSH="ssh -i $KEY -o StrictHostKeyChecking=yes"

# Vérifié avant tout transfert : sur une base neuve, personne n'a de rôle et le
# back-office reste fermé à tout le monde. Le découvrir après le déploiement oblige à
# repasser par la base à la main.
: "${ADMIN_EMAILS:?Set ADMIN_EMAILS (comma-separated) — nobody could open the back-office without it}"

echo "==> Checking SSH $REMOTE"
"${SSH[@]}" "$REMOTE" 'id; sudo -n true'

echo "==> Ensuring /opt dirs owned by emmy"
"${SSH[@]}" "$REMOTE" "sudo mkdir -p '${SRC_DIR}' /opt/app && sudo chown -R emmy:emmy /opt/src /opt/app"

# Le monorepo entier, front compris : `deploy.sh` construit les deux images sur place.
# `node_modules/` et `.venv/` sont exclus — des centaines de mégaoctets reconstruits de
# toute façon dans les images.
echo "==> Sync monorepo source"
rsync -az --delete \
  --exclude '.git/' --exclude '.cache/' --exclude '__pycache__/' \
  --exclude '.venv/' --exclude 'node_modules/' --exclude 'dist/' \
  --exclude 'tests/' --exclude 'docs/' --exclude '.env' \
  -e "$RSYNC_SSH" \
  "$ROOT/" "$REMOTE:${SRC_DIR}/"

echo "==> Sync deploy assets"
rsync -az -e "$RSYNC_SSH" \
  "$ROOT/infra/kvm1/docker-compose.yml" \
  "$ROOT/infra/kvm1/Caddyfile" \
  "$ROOT/infra/kvm1/Caddyfile.http-dev" \
  "$ROOT/infra/kvm1/deploy.sh" \
  "$REMOTE:/opt/app/"

PG_PASS="${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}"
JWT="${JWT_SECRET:-$(openssl rand -hex 32)}"
INTERNAL_KEY="${INTERNAL_API_KEY:-$(openssl rand -base64 32 | tr -d '=+/')}"
SALT="${ANALYTICS_IP_SALT:-$(openssl rand -hex 16)}"
TAG="${APP_TAG:-$(cd "$ROOT" && git rev-parse --short HEAD)}"

echo "==> Writing /opt/app/.env (secrets stay on the VPS only)"
"${SSH[@]}" "$REMOTE" bash -s <<EOF
set -euo pipefail
cd /opt/app
chmod +x deploy.sh
mkdir -p data sites
# Profil HTTP tant qu'aucun domaine ne pointe ici. Avec un domaine : restaurer
# Caddyfile (ACME), puis passer DOMAIN, PUBLIC_BASE_URL, APP_BASE_URL, CORS_ORIGINS
# et APP_ENV=production ensemble.
cp -f Caddyfile.http-dev Caddyfile

umask 077
cat > .env <<'ENV'
# Wayhost production — jamais commité. Référence commentée : infra/kvm1/.env.example
DOMAIN=:80
DEPLOY_MODE=local
SRC_DIR=${SRC_DIR}
CI_REGISTRY_IMAGE=jarvis-api
FRONTEND_IMAGE=jarvis-web
FRONTEND_TAG=${TAG}
APP_TAG=${TAG}
APP_PORT=8080
APP_HOST=0.0.0.0

# APP_ENV reste 'development' tant que l'accès se fait par IP en HTTP : en
# 'production', settings.validate() refuse — à raison — de démarrer sans HTTPS ni
# CORS_ORIGINS explicite. À basculer en même temps que le domaine.
APP_ENV=development
PUBLIC_BASE_URL=http://${HOST}
APP_BASE_URL=http://${HOST}
CORS_ORIGINS=*
LOG_LEVEL=INFO
LOG_JSON=true
DATA_DIR=data
SITES_DIR=sites

POSTGRES_USER=jarvis
POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_DB=jarvis
DATABASE_URL=postgresql://jarvis:${PG_PASS}@db:5432/jarvis

# La génération passe par la file ; le service \`worker\` la dépile.
JOB_MODE=queue
JOB_CONCURRENCY=2

GEMINI_MOCK=false
GEMINI_CODER_MODEL=gemini-2.5-flash
GEMINI_REVIEWER_MODEL=gemini-2.5-flash
GEMINI_TEMPERATURE=0.7
GEMINI_MAX_OUTPUT_TOKENS=32768
GEMINI_TIMEOUT_S=180
# À renseigner sur le VPS après l'amorçage — jamais de clé réelle dans ce dépôt.
GEMINI_API_KEY=

JWT_SECRET=${JWT}
JWT_EXPIRE_MINUTES=120
INTERNAL_API_KEY=${INTERNAL_KEY}
ADMIN_EMAILS=${ADMIN_EMAILS}
ANALYTICS_IP_SALT=${SALT}

APP_MEM_LIMIT=1024m
APP_CPUS=0.50
WORKER_MEM_LIMIT=1024m
WORKER_CPUS=0.50
FRONTEND_MEM_LIMIT=64m
FRONTEND_CPUS=0.15
CADDY_MEM_LIMIT=64m
CADDY_CPUS=0.15
POSTGRES_MEM_LIMIT=512m
POSTGRES_CPUS=0.30
ENV

# Ré-applique le DROP sur le port Redis sortant (scan constaté depuis cette machine).
sudo iptables -C OUTPUT -p tcp --dport 6379 -j DROP 2>/dev/null || sudo iptables -I OUTPUT 1 -p tcp --dport 6379 -j DROP
sudo iptables -C OUTPUT -p udp --dport 6379 -j DROP 2>/dev/null || sudo iptables -I OUTPUT 1 -p udp --dport 6379 -j DROP

./deploy.sh

echo "==> Health"
curl -fsS -m 5 http://127.0.0.1/healthz || curl -fsS -m 5 http://127.0.0.1:8080/healthz || true
echo
echo -n "syn-sent 6379: "; ss -tn state syn-sent 2>/dev/null | grep -c ':6379' || echo 0
docker compose ps
EOF

echo "==> Done. Demo URL: http://${HOST}/"
echo "    Renseigner GEMINI_API_KEY dans /opt/app/.env, puis : docker compose up -d app worker"
