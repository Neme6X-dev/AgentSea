# Raccourcis de développement du monorepo Jarvis.
#
# Objectif : qu'un nouvel arrivant n'ait pas à retrouver quel virtualenv activer, dans
# quel dossier lancer quoi, ni quelles variables exporter. Chaque cible est autonome.

API  := apps/api
WEB  := apps/web
PY   := $(API)/.venv/bin/python
PIP  := $(API)/.venv/bin/pip

# Bases de données locales. `?=` pour qu'un développeur qui a déjà un PostgreSQL
# ailleurs surcharge depuis son environnement sans toucher au fichier.
#
# Port 55432 et non 5432 : la plupart des machines de développement font déjà tourner
# un PostgreSQL — celui d'un autre projet, ou celui du système. `make db-dev` sur 5432
# échouait alors au démarrage du conteneur, ou pire, se connectait silencieusement à la
# base d'à côté. Un port dédié rend le conflit impossible.
DB_PORT           ?= 55432
DATABASE_URL      ?= postgresql://jarvis:jarvis@127.0.0.1:$(DB_PORT)/jarvis
TEST_DATABASE_URL ?= postgresql://jarvis:jarvis@127.0.0.1:$(DB_PORT)/jarvis_test

.DEFAULT_GOAL := help
.PHONY: help install install-api install-web migrate api worker web build test test-api lint clean db-dev

help:  ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: install-api install-web  ## Installe toutes les dépendances

install-api:  ## Crée le virtualenv de l'API et installe ses dépendances
	@test -d $(API)/.venv || python3 -m venv $(API)/.venv
	@$(PIP) install -q -r $(API)/requirements-dev.txt
	@test -f $(API)/.env || cp $(API)/.env.example $(API)/.env
	@echo "API prête. Complétez $(API)/.env (JWT_SECRET, DATABASE_URL, ADMIN_EMAILS)."

install-web:  ## Installe les dépendances de l'interface
	@cd $(WEB) && npm install --no-audit --no-fund
	@test -f $(WEB)/.env || cp $(WEB)/.env.example $(WEB)/.env

migrate:  ## Applique les migrations Alembic
	@cd $(API) && .venv/bin/alembic upgrade head

api:  ## Démarre l'API en rechargement automatique
	@cd $(API) && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

worker:  ## Démarre un worker de la file de travaux
	@cd $(API) && .venv/bin/python -m app.jobs.worker

web:  ## Démarre l'interface
	@cd $(WEB) && npm run dev

build:  ## Construit l'interface pour la production
	@cd $(WEB) && npm run build

test: test-api build  ## Lance les tests de l'API puis vérifie la construction du front

test-api:  ## Lance la suite de tests de l'API
	@cd $(API) && GEMINI_MOCK=true JOB_MODE=inline \
		TEST_DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/python -m pytest tests/ -q

db-dev:  ## Lance un PostgreSQL de développement dans Docker (idempotent)
	@docker start jarvis-pg 2>/dev/null \
		|| docker run -d --name jarvis-pg \
			-e POSTGRES_USER=jarvis -e POSTGRES_PASSWORD=jarvis -e POSTGRES_DB=jarvis \
			-p $(DB_PORT):5432 postgres:16-alpine
	@printf 'Attente de PostgreSQL'
	@until docker exec jarvis-pg pg_isready -U jarvis -q 2>/dev/null; do printf '.'; sleep 1; done; echo " prêt."
	@# La base de test est créée ici plutôt que par la suite de tests : celle-ci se
	@# connecte à `jarvis_test` pour créer le schéma, elle ne peut donc pas créer la
	@# base elle-même. Sans cette ligne, `make test-api` échouait sur une machine neuve
	@# avec une erreur qui désignait la connexion, pas la base manquante.
	@docker exec jarvis-pg psql -U jarvis -d jarvis -c 'CREATE DATABASE jarvis_test OWNER jarvis' 2>/dev/null \
		|| true
	@echo "DATABASE_URL=$(DATABASE_URL)"
	@echo "TEST_DATABASE_URL=$(TEST_DATABASE_URL)"

clean:  ## Supprime les artefacts de construction et les caches
	@rm -rf $(WEB)/dist $(WEB)/node_modules/.vite
	@find $(API) -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(API)/.pytest_cache
