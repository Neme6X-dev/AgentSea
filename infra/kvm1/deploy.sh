#!/usr/bin/env bash
# Rolling deploy for Wayhost KVM1.
# Modes:
#   DEPLOY_MODE=local    (default) — build image on the VPS (no GitLab registry)
#   DEPLOY_MODE=registry — docker login + pull from CI_REGISTRY_IMAGE
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

: "${CI_REGISTRY_IMAGE:?Set CI_REGISTRY_IMAGE in .env (e.g. jarvis-api)}"
: "${APP_TAG:?Set APP_TAG (e.g. commit sha)}"

DEPLOY_MODE="${DEPLOY_MODE:-local}"
# Racine du monorepo, pas `apps/api` : l'image de l'API embarque
# `packages/templates/catalog`, qui vit en dehors du dossier de l'API.
SRC_DIR="${SRC_DIR:-/opt/src/agentsea}"

: "${FRONTEND_IMAGE:?Set FRONTEND_IMAGE in .env (e.g. registry…/frontend-jarvis)}"
: "${FRONTEND_TAG:?Set FRONTEND_TAG in .env (e.g. commit sha)}"

mkdir -p data sites

# Le conteneur applicatif tourne en uid 10001 (appuser). Le chown du Dockerfile est fait
# à la construction et se retrouve masqué par les bind mounts : sans cet alignement, la
# première génération échoue en PermissionError sur sites/, avec un symptôme trompeur
# (« la génération échoue ») qui ne désigne pas la cause.
APP_UID="${APP_UID:-10001}"
if [[ "$(stat -c %u data)" != "$APP_UID" || "$(stat -c %u sites)" != "$APP_UID" ]]; then
  echo "==> Aligning data/ and sites/ ownership on uid ${APP_UID}"
  # Prefer direct chown; then passwordless sudo; then Docker (works for gitlab-runner in docker group).
  if chown -R "${APP_UID}:${APP_UID}" data sites 2>/dev/null; then
    :
  elif sudo -n chown -R "${APP_UID}:${APP_UID}" data sites 2>/dev/null; then
    :
  else
    docker run --rm \
      -v "$(pwd)/data:/data" \
      -v "$(pwd)/sites:/sites" \
      alpine:3.20 \
      chown -R "${APP_UID}:${APP_UID}" /data /sites
  fi
fi

if [[ "$DEPLOY_MODE" == "registry" ]]; then
  if [[ -n "${CI_REGISTRY:-}" && -n "${CI_REGISTRY_USER:-}" && -n "${CI_REGISTRY_PASSWORD:-}" ]]; then
    echo "$CI_REGISTRY_PASSWORD" | docker login "$CI_REGISTRY" -u "$CI_REGISTRY_USER" --password-stdin
  fi
  echo "==> Pulling images from registry (app + web + db + edge)"
  docker compose pull || true
else
  echo "==> Local build mode (GitLab Container Registry unavailable)"
  if [[ ! -f "${SRC_DIR}/apps/api/Dockerfile" ]]; then
    echo "Missing ${SRC_DIR}/apps/api/Dockerfile — sync the monorepo to ${SRC_DIR} first" >&2
    exit 1
  fi
  # Le catalogue de gabarits est copié dans l'image. Absent, la génération continue de
  # fonctionner mais sans repère de structure, et rien ne le signale : on le vérifie ici.
  if [[ ! -d "${SRC_DIR}/packages/templates/catalog" ]]; then
    echo "Missing ${SRC_DIR}/packages/templates/catalog — incomplete sync" >&2
    exit 1
  fi
  echo "==> Building ${CI_REGISTRY_IMAGE}:${APP_TAG} on VPS"
  docker build -f "${SRC_DIR}/apps/api/Dockerfile" \
    -t "${CI_REGISTRY_IMAGE}:${APP_TAG}" -t "${CI_REGISTRY_IMAGE}:latest" "$SRC_DIR"

  # Le front aussi est construit sur place. Compose exige `FRONTEND_IMAGE` (`:?`) : sans
  # cette étape, un déploiement en mode local s'arrêtait sur une image que personne
  # n'avait poussée, et la seule issue documentée était un registre.
  #
  # `VITE_API_BASE_URL` reste vide à dessein : le front et l'API sont servis par le même
  # Caddy, sur la même origine. Y mettre une URL absolue rendrait le front dépendant du
  # domaine au moment de la construction — un changement de domaine imposerait de
  # reconstruire l'image au lieu de modifier une variable.
  echo "==> Building ${FRONTEND_IMAGE}:${FRONTEND_TAG} on VPS"
  docker build -t "${FRONTEND_IMAGE}:${FRONTEND_TAG}" -t "${FRONTEND_IMAGE}:latest" \
    "${SRC_DIR}/apps/web"

  echo "==> Pulling db + edge (best-effort)"
  docker compose pull db edge || true
fi

echo "==> Recreating stack"
# Prefer images already on the VPS (local build / previously pulled). Avoid a hard
# failure when the registry rejects a tag or a malformed host (:443 in the name).
docker compose up -d --remove-orphans --pull never

echo "==> Waiting for app health (/healthz)"
for i in $(seq 1 45); do
  if docker compose ps app | grep -q "(healthy)"; then
    echo "==> App healthy"
    break
  fi
  if [[ "$i" -eq 45 ]]; then
    echo "==> Healthcheck failed — check: docker compose logs app db" >&2
    docker compose ps >&2 || true
    exit 1
  fi
  sleep 2
done

# Le worker n'a pas de healthcheck : il ne sert aucune requête, il n'y a rien à
# interroger. On vérifie donc qu'il tourne — un worker absent ou en boucle de
# redémarrage laisse la file grossir sans que l'API, elle, cesse d'être verte.
echo "==> Checking queue worker"
if ! docker compose ps worker --status running --quiet | grep -q .; then
  echo "==> Worker not running — generations would queue forever." >&2
  docker compose logs --tail 40 worker >&2 || true
  exit 1
fi
echo "==> Worker running"

echo "==> Pruning unused images"
docker image prune -f

echo "==> Status"
docker compose ps
docker stats --no-stream || true
free -h | head -n 2
