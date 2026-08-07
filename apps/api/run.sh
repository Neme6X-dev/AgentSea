#!/usr/bin/env bash
# Lancement du backend de la plateforme (générateur de sites vitrines).
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Création du venv…"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "Création de .env depuis .env.example (à compléter : GEMINI_API_KEY, JWT_SECRET)…"
  cp .env.example .env
fi

# Génère un JWT_SECRET s'il manque OU s'il est resté sur une valeur de remplissage.
# Un secret devinable permet de forger des jetons pour n'importe quel utilisateur : le
# laisser passer parce que la ligne « n'est pas vide » est précisément le piège à éviter.
if grep -qE '^JWT_SECRET=(|__GENERE_AU_PREMIER_RUN__|changeme|secret)$' .env; then
  SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s|^JWT_SECRET=.*$|JWT_SECRET=$SECRET|" .env
  echo "JWT_SECRET généré (les jetons existants sont invalidés)."
fi

# Même logique pour la clé de service consommée par n8n.
if grep -qE '^INTERNAL_API_KEY=(|changeme)$' .env; then
  KEY=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))")
  sed -i "s|^INTERNAL_API_KEY=.*$|INTERNAL_API_KEY=$KEY|" .env
  echo "INTERNAL_API_KEY généré — à reporter dans les workflows n8n."
fi

# Vérifie que DATABASE_URL est renseigné (PostgreSQL requis)
if ! grep -qE '^DATABASE_URL=.+' .env; then
  echo "ERREUR : DATABASE_URL manquant dans .env (ex: postgresql://jarvis:jarvis@127.0.0.1:55432/jarvis)"
  exit 1
fi

echo "Application des migrations Alembic…"
.venv/bin/alembic upgrade head

HOST=$(.venv/bin/python -c "import os;from app.config import settings;print(settings.app_host)")
PORT=$(.venv/bin/python -c "import os;from app.config import settings;print(settings.app_port)")

echo "Démarrage sur http://$HOST:$PORT (docs : /docs)"
# `python -m uvicorn` plutôt que le script .venv/bin/uvicorn : selon la façon dont le
# venv a été créé, ce dernier peut ne pas exister alors que le module est importable.
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
