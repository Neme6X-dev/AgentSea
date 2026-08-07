# Image de l'API.
#
# ATTENTION : le contexte de construction est la **racine du monorepo**, pas ce
# dossier :
#
#     docker build -f apps/api/Dockerfile .
#
# La raison est le catalogue de gabarits. Il vit dans `packages/templates/catalog`,
# partagé entre l'API et le front (cf. docs/ARCHITECTURE.md §10). Construite depuis
# `apps/api/`, l'image ne pouvait pas l'atteindre : `settings.templates_dir` retombait
# sur `app/templates`, qui n'existait pas davantage, et `catalog()` renvoyait un tuple
# vide **sans rien journaliser**. La plateforme démarrait, générait des sites, passait
# son healthcheck — mais le codeur travaillait sans repère de structure. C'est
# exactement le genre de panne que l'on ne voit pas : il faut comparer la qualité des
# sites produits pour la soupçonner.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Alembic est la source de vérité du schéma : sans ces deux entrées, init_db() ne peut
# pas appliquer les migrations dans le conteneur.
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

# Catalogue de gabarits, à l'emplacement de repli prévu par `settings.templates_dir`.
# L'image reste ainsi autonome : elle n'a pas besoin que le monorepo soit présent sur
# le serveur à l'exécution, seulement à la construction.
COPY packages/templates/catalog ./app/templates

RUN mkdir -p /app/data /app/sites \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${APP_PORT}/healthz" || exit 1

# Le processus web. Le worker de la file utilise la **même image** avec une autre
# commande (cf. infra/kvm1/docker-compose.yml, service `worker`) : les deux exécutent
# le même code d'agents, les faire diverger produirait des générations différentes
# selon le chemin emprunté.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
