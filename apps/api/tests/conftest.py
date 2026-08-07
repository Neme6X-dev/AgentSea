"""Configuration pytest de la plateforme.

- DB de test : PostgreSQL réel, base dédiée, schéma purgé entre chaque test.
- Gemini en mode mock (déterminisme, aucun réseau).

Le défaut pointe sur le PostgreSQL que `make db-dev` lance, et non sur la machine de
quelqu'un : un défaut nominatif ne marche que pour son auteur, et le reste de l'équipe
découvre le problème sous la forme de deux cent vingt-quatre tests en erreur.

La base de test est **créée si elle n'existe pas**. Sans cela, `make db-dev` suivi de
`make test-api` échoue sur une base absente — un premier contact décourageant pour une
étape qui n'a rien de métier.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Aligné sur `make db-dev` (postgres:16-alpine, identifiants `jarvis`). La base porte
#: un nom distinct de celle de développement : la suite fait `drop_all` entre chaque
#: test, et viser la base de travail effacerait les données locales sans prévenir.
DEFAULT_TEST_DB_URL = "postgresql://jarvis:jarvis@127.0.0.1:5432/jarvis_test"

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

os.environ.setdefault("GEMINI_MOCK", "true")
os.environ.setdefault("JWT_SECRET", "test-secret-pour-tests")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")

from app import db  # noqa: E402
from app.config import settings  # noqa: E402


def _maintenance_url(url: str) -> str:
    """Même serveur, base `postgres` — celle qui existe toujours.

    Le schéma est forcé sur `postgresql+psycopg` comme le fait `db.configure_engine` :
    seul psycopg 3 est installé, et un `postgresql://` nu fait chercher psycopg2 à
    SQLAlchemy, qui échoue sur un `ModuleNotFoundError` sans rapport avec le test.
    """
    parts = urlsplit(url)
    scheme = parts.scheme if "+" in parts.scheme else "postgresql+psycopg"
    return urlunsplit((scheme, parts.netloc, "/postgres", parts.query, parts.fragment))


def _database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def _ensure_database(url: str) -> None:
    """Crée la base de test si elle manque, ou interrompt la session avec un message utile.

    Un serveur injoignable fait échouer la connexion de *chaque* test, avec la même
    trace SQLAlchemy répétée deux cents fois et un temps d'attente qui dépasse les
    huit minutes. On préfère une seule ligne, tout de suite, qui dit quoi lancer.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    name = _database_name(url)
    # `connect_timeout` borne l'attente : sans lui, un hôte qui ne répond pas
    # (conteneur éteint, port fermé) tient la session pendant des minutes.
    admin = create_engine(
        _maintenance_url(url),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).scalar()
            if not exists:
                # Le nom vient de la configuration, pas d'une requête : il ne peut pas
                # être paramétré dans un DDL, mais il n'est pas non plus une entrée.
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    except SQLAlchemyError as exc:
        pytest.exit(
            "PostgreSQL injoignable pour la suite de tests.\n"
            f"  URL essayée : {url}\n"
            f"  Cause       : {type(exc).__name__}: {exc}\n\n"
            "  Lancez une base de développement :  make db-dev\n"
            "  ou pointez ailleurs :               TEST_DATABASE_URL=postgresql://… make test-api\n\n"
            "  La suite exige un PostgreSQL réel : le schéma utilise des types et des\n"
            "  verrous (SKIP LOCKED) que SQLite ne reproduit pas.",
            returncode=1,
        )
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    _ensure_database(TEST_DB_URL)
    return TEST_DB_URL


@pytest.fixture(autouse=True)
def _clean_db(database_url: str):
    """Avant chaque test : moteur vers la DB de test, schéma purgé."""
    db.configure_engine(database_url)
    # purge (create_all ne drop pas) : drop_all puis create_all
    db.Base.metadata.drop_all(db.get_engine())
    db.Base.metadata.create_all(db.get_engine())
    yield
    db.Base.metadata.drop_all(db.get_engine())


@pytest.fixture
def clean_engine():
    """Moteur de test déjà configuré (les tables existent après _clean_db)."""
    return db.get_engine()
