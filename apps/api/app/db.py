"""Persistance de la plateforme (PostgreSQL) via SQLAlchemy 2.0 (sync).

Ce module porte **tout le schéma** — c'est ce qui permet à Alembic d'autogénérer les
migrations sans rien manquer. La logique de lecture spécialisée vit en revanche dans
les modules métier (`app.jobs.queue`, `app.analytics.*`), qui empruntent `session_scope()` :
concentrer ici les modèles évite les schémas fantômes, y concentrer aussi les requêtes
produirait un fichier de deux mille lignes que plus personne ne relit.

Les accesseurs publics renvoient des `dict` aux horodatages sérialisés en ISO 8601.
C'est un choix de contrat, pas une facilité : les modèles Pydantic exposent
`created_at: str`, et les routeurs comme le front s'appuient dessus. Le stockage, lui,
utilise de vrais `timestamptz` — sans quoi les agrégations du dashboard admin
(« sites publiés par semaine ») exigeraient de découper des chaînes de caractères.
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.orm import Session as OrmSession

from app.config import BASE_DIR, settings
from app.utils import slugify

logger = logging.getLogger("app.db")


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Modèles — comptes
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        UniqueConstraint("google_sub"),
        UniqueConstraint("github_id"),
        Index("ix_users_role", "role"),
        Index("ix_users_plan", "plan"),
        Index("ix_users_country", "country"),
        Index("ix_users_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(191), nullable=True)
    github_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- Rôle et abonnement ------------------------------------------------- #
    # `role` gouverne l'accès au back-office ; `plan` gouverne les quotas. Les deux
    # sont distincts : un administrateur de la plateforme n'est pas un client premium,
    # et un client Agence n'a rien à faire dans le dashboard interne.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    plan: Mapped[str] = mapped_column(String(24), nullable=False, default="decouverte")
    plan_period: Mapped[str] = mapped_column(String(8), nullable=False, default="monthly")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # --- Contexte régional -------------------------------------------------- #
    # Le pays n'est pas décoratif : il détermine la devise de facturation, le taux de
    # TVA, l'indicatif proposé à l'inscription et le tarif appliqué.
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="BJ")
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(24), nullable=True)  # E.164
    whatsapp: Mapped[str | None] = mapped_column(String(24), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    locale: Mapped[str] = mapped_column(String(5), nullable=False, default="fr")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Subscription(Base):
    """Historique d'abonnement — la source du chiffre d'affaires du dashboard.

    Une ligne par période facturée, jamais mise à jour après encaissement : c'est ce
    qui permet de recalculer un MRR passé à l'identique, même après un changement de
    grille tarifaire.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subs_user", "user_id"), Index("ix_subs_started", "started_at"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan: Mapped[str] = mapped_column(String(24), nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False, default="monthly")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF")
    #: Montant normalisé en FCFA — indispensable pour additionner des paiements
    #: encaissés en naira, en rand et en franc CFA dans un même graphique.
    amount_xof: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="BJ")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageCounter(Base):
    """Compteurs de consommation par période de facturation.

    Un compteur incrémenté vaut mieux qu'un `COUNT(*)` à la volée : le contrôle de
    quota s'exécute avant chaque génération, sur le chemin critique, et doit rester à
    coût constant quand un compte accumule des milliers de sessions.
    """

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("user_id", "period", "metric", name="uq_usage_user_period_metric"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # AAAA-MM
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


# --------------------------------------------------------------------------- #
# Modèles — sites générés
# --------------------------------------------------------------------------- #
class SiteSession(Base):
    """Une session = un site en construction.

    Le modèle s'appelle `SiteSession` et non `Session` : l'ancien nom masquait
    `sqlalchemy.orm.Session` importé dans ce même module, ce qui rendait toute
    annotation de type trompeuse. Le nom de table, lui, reste `sessions` — l'API
    publique et les migrations existantes en dépendent.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user", "user_id"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_created_at", "created_at"),
        Index("ix_sessions_country", "country"),
    )

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    steps: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    site_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Enrichissements produit -------------------------------------------- #
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="BJ")
    business_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(String(191), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("session_id", "kind", "version"),
        Index("ix_artifacts_session_kind", "session_id", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class SiteVisit(Base):
    """Fréquentation quotidienne agrégée d'un site publié.

    Agrégée à l'écriture, et non stockée visite par visite : un site à succès
    produirait des millions de lignes dont le dashboard ne tire qu'une courbe
    journalière. Une ligne par (site, jour, pays) suffit à tout ce qu'on affiche, et
    l'ensemble reste interrogeable sans entrepôt de données.
    """

    __tablename__ = "site_visits"
    __table_args__ = (
        UniqueConstraint("session_id", "day", "country", name="uq_visit_session_day_country"),
        Index("ix_visits_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # AAAA-MM-JJ
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="??")
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visitors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Clics sur les canaux de contact — c'est la seule conversion qui compte pour un
    #: site vitrine africain, bien avant le temps passé sur la page.
    whatsapp_clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# --------------------------------------------------------------------------- #
# Modèles — exploitation
# --------------------------------------------------------------------------- #
class Job(Base):
    """Travail de fond durable (génération, édition, publication).

    Remplace les `asyncio.create_task` du premier prototype. La différence est
    structurelle : une tâche asyncio meurt avec le processus qui l'a lancée. Un
    redémarrage, un déploiement ou un `OOMKilled` en pleine génération laissait la
    session bloquée en « en cours » pour toujours, et le front interrogeait dans le
    vide. Ici, le travail survit au processus et un autre exécutant le reprend.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "status", "priority", "run_at"),
        Index("ix_jobs_session", "session_id"),
        Index("ix_jobs_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    #: Plus la valeur est basse, plus le travail passe tôt (cf. billing.quotas).
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    """Événement produit : la matière première de tous les graphiques du dashboard.

    L'IP n'est jamais stockée en clair, seulement un condensat tronqué : elle sert à
    distinguer deux visiteurs, jamais à en identifier un. Le pays, lui, est conservé —
    c'est la dimension d'analyse la plus utile sur un marché multi-pays.
    """

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_name_ts", "name", "ts"),
        Index("ix_events_user", "user_id"),
        Index("ix_events_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    props: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ip_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


class LlmCall(Base):
    """Un appel au fournisseur de modèle : coût, latence, issue.

    Sans cette table, le poste de dépense le plus volatil de la plateforme est
    invisible jusqu'à la facture. Avec elle, le dashboard répond à « combien me coûte
    un site généré » — la question qui conditionne toute la tarification.
    """

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_ts", "ts"), Index("ix_llm_agent", "agent"), Index("ix_llm_session", "session_id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_xof: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    key_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuditLog(Base):
    """Trace des actions d'administration.

    Ce que fait un administrateur sur le compte d'un client — suspendre, changer
    d'offre, republier — doit rester explicable des mois plus tard. On conserve
    l'e-mail de l'acteur en plus de son identifiant : un compte supprimé ne doit pas
    effacer la trace de ce qu'il a fait.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_ts", "ts"), Index("ix_audit_actor", "actor_id"), Index("ix_audit_target", "target_type", "target_id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changes: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeatureFlag(Base):
    """Interrupteur de fonctionnalité, pilotable depuis le back-office.

    Permet d'ouvrir un pays, d'activer un nouveau modèle ou de couper une intégration
    défaillante sans redéployer — utile quand l'équipe et le VPS sont sur des fuseaux
    et des connexions qui ne se prêtent pas à un déploiement d'urgence.
    """

    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(254), nullable=True)


class AuthAttempt(Base):
    """Tentatives d'authentification échouées, pour un rate-limit qui tient la charge.

    Le compteur en mémoire du prototype protégeait un unique processus : derrière
    plusieurs workers uvicorn, dix tentatives autorisées en devenaient dix par worker,
    et un redémarrage remettait tout à zéro. En base, la limite est réellement globale.
    """

    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_key_ts", "key", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(320), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


# --------------------------------------------------------------------------- #
# Moteur & sessions
# --------------------------------------------------------------------------- #
_engine: Engine | None = None
_session_factory: sessionmaker[OrmSession] | None = None


def configure_engine(database_url: str | None = None) -> Engine:
    """Initialise le moteur (override possible pour les tests)."""
    global _engine, _session_factory
    url = database_url or settings.database_url
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("postgres"):
        # psycopg 3 : schéma postgresql+psycopg pour SQLAlchemy
        if not url.startswith("postgresql+"):
            url = "postgresql+psycopg://" + url.split("://", 1)[1]
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_max_overflow
        engine_kwargs["pool_recycle"] = settings.db_pool_recycle_s
    _engine = create_engine(url, **engine_kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    """Retourne le moteur (l'initialise une fois si besoin)."""
    if _engine is None:
        configure_engine()
    return _engine  # type: ignore[return-value]


def _session() -> OrmSession:
    """Ouvre une session (utilisée comme contexte: with _session() as s:)."""
    if _session_factory is None:
        configure_engine()
    return _session_factory()  # type: ignore[operator]


@contextmanager
def session_scope() -> Iterator[OrmSession]:
    """Session transactionnelle pour les modules métier.

    Valide en sortie normale, annule sur exception. C'est le point d'entrée que
    `app.jobs` et `app.analytics` empruntent : ils manipulent les modèles définis
    ici sans avoir à connaître la configuration du moteur.
    """
    session = _session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _now() -> str:
    """Horodatage ISO 8601 UTC, format d'échange de toute l'API."""
    return _utcnow().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Initialisation
# --------------------------------------------------------------------------- #
def init_db() -> None:
    """Applique le schéma via Alembic. Échoue si les migrations ne passent pas.

    Le repli silencieux sur `create_all()` a été retiré : il produisait une base au
    schéma correct mais **sans table de version Alembic**, que les révisions suivantes
    ne savaient plus faire évoluer. Le symptôme n'apparaissait qu'au premier changement
    de schéma, en production, sur des données réelles.

    Un démarrage qui échoue bruyamment ici est préférable : le healthcheck du conteneur
    le détecte et le déploiement précédent reste en place.
    """
    try:
        run_migrations()
    except Exception as exc:
        logger.error("Migrations Alembic en échec : %s", exc)
        raise


def run_migrations() -> None:
    """Applique les migrations Alembic sur le moteur courant (upgrade head)."""
    from alembic import command
    from alembic.config import Config

    url = settings.database_url
    if url.startswith("postgres") and not url.startswith("postgresql+"):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.upgrade(cfg, "head")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _dict(obj: Any) -> dict[str, Any]:
    """Modèle → dict, horodatages en ISO et colonnes JSON décodées.

    La conversion des `datetime` se fait ici, à la frontière : le stockage reste typé
    (indispensable aux agrégations) tandis que les routeurs, Pydantic et le front
    continuent de voir des chaînes ISO, comme le contrat le prévoit.
    """
    d: dict[str, Any] = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        d[column.name] = value.isoformat(timespec="seconds") if isinstance(value, datetime) else value
    return _decode_json(d)


def _decode_json(d: dict[str, Any]) -> dict[str, Any]:
    for key in ("steps", "payload", "props", "changes"):
        raw = d.get(key)
        if isinstance(raw, str) and raw:
            try:
                d[key] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return d


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def create_user(
    email: str,
    *,
    password_hash: str | None = None,
    provider: str = "local",
    name: str | None = None,
    google_sub: str | None = None,
    github_id: str | None = None,
    country: str = "BJ",
    phone: str | None = None,
    company: str | None = None,
    locale: str = "fr",
    role: str = "user",
    plan: str = "decouverte",
) -> dict[str, Any] | None:
    with _session() as s:
        try:
            row = User(
                email=email.lower(),
                password_hash=password_hash,
                provider=provider,
                name=name,
                google_sub=google_sub,
                github_id=github_id,
                country=(country or "BJ").upper()[:2],
                phone=phone,
                company=company,
                locale=locale,
                role=role,
                plan=plan,
                created_at=_utcnow(),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return _dict(row)
        except Exception:
            s.rollback()
            return None


def _get_user_by(session, **filters) -> dict[str, Any] | None:
    row = session.query(User).filter_by(**filters).first()
    return _dict(row) if row else None


def get_user(user_id: int) -> dict[str, Any] | None:
    with _session() as s:
        row = s.get(User, user_id)
        return _dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _session() as s:
        return _get_user_by(s, email=email.lower())


def get_user_by_google_sub(google_sub: str) -> dict[str, Any] | None:
    with _session() as s:
        return _get_user_by(s, google_sub=google_sub)


def get_user_by_github_id(github_id: str) -> dict[str, Any] | None:
    with _session() as s:
        return _get_user_by(s, github_id=github_id)


def link_google_sub(user_id: int, google_sub: str) -> None:
    with _session() as s:
        s.query(User).filter_by(id=user_id).update({"google_sub": google_sub, "provider": "google"})
        s.commit()


def link_github_id(user_id: int, github_id: str) -> None:
    with _session() as s:
        s.query(User).filter_by(id=user_id).update({"github_id": github_id, "provider": "github"})
        s.commit()


def update_user(user_id: int, **fields: Any) -> dict[str, Any] | None:
    """Met à jour un compte en n'acceptant que des colonnes connues.

    Le filtrage sur `_USER_WRITABLE` n'est pas défensif par principe : cette fonction
    est appelée depuis le back-office avec un corps de requête, et laisser passer une
    clé arbitraire y transformerait une faute de frappe en écriture silencieuse — ou
    permettrait de fixer `role` depuis un endpoint qui ne le prévoit pas.
    """
    updates = {k: v for k, v in fields.items() if k in _USER_WRITABLE}
    if not updates:
        return get_user(user_id)
    with _session() as s:
        s.query(User).filter_by(id=user_id).update(updates)
        s.commit()
    return get_user(user_id)


_USER_WRITABLE = {
    "name", "role", "plan", "plan_period", "status", "country", "city", "phone",
    "whatsapp", "company", "locale", "last_seen_at", "suspended_at", "suspension_reason",
}


def touch_user(user_id: int) -> None:
    """Note le passage d'un utilisateur (calcul des actifs quotidiens/mensuels)."""
    with _session() as s:
        s.query(User).filter_by(id=user_id).update({"last_seen_at": _utcnow()})
        s.commit()


def count_users(**filters: Any) -> int:
    with _session() as s:
        return s.query(User).filter_by(**filters).count()


# --------------------------------------------------------------------------- #
# Sessions (sites)
# --------------------------------------------------------------------------- #
def create_session(
    user_id: int,
    prompt: str,
    slug: str,
    *,
    country: str = "BJ",
    business_type: str | None = None,
) -> str:
    sid = uuid.uuid4().hex[:12]
    now = _utcnow()
    with _session() as s:
        s.add(
            SiteSession(
                id=sid, user_id=user_id, slug=slug, prompt=prompt, status="pending",
                country=(country or "BJ").upper()[:2], business_type=business_type,
                created_at=now, updated_at=now,
            )
        )
        s.commit()
    return sid


def allocate_slug(prompt: str) -> str:
    """Alloue un slug unique globalement (boucle sur get_session_by_slug)."""
    base = slugify(prompt)
    slug = base
    counter = 1
    while get_session_by_slug(slug) is not None:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def update_step(session_id: str, step_name: str, step_status: str, detail: str = "") -> None:
    now = _utcnow()
    with _session() as s:
        row = s.get(SiteSession, session_id)
        if row is None:
            return
        steps = json.loads(row.steps) if row.steps else []
        steps.append(
            {"step": step_name, "status": step_status, "detail": detail, "ts": now.isoformat(timespec="seconds")}
        )
        row.steps = json.dumps(steps, ensure_ascii=False)
        row.current_step = step_name
        # Le statut global suit l'étape sauf quand une étape finit "done"
        # (on ne doit pas écraser un statut terminal comme "deployed").
        if step_status != "done":
            row.status = step_status
        row.updated_at = now
        s.commit()


def set_session_field(session_id: str, **fields: Any) -> None:
    now = _utcnow()
    data: dict[str, Any] = {}
    for k, v in fields.items():
        data[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    with _session() as s:
        s.query(SiteSession).filter_by(id=session_id).update({**data, "updated_at": now})
        s.commit()


def get_session(session_id: str) -> dict[str, Any] | None:
    with _session() as s:
        row = s.get(SiteSession, session_id)
        return _dict(row) if row else None


def get_session_by_slug(slug: str) -> dict[str, Any] | None:
    with _session() as s:
        row = s.query(SiteSession).filter_by(slug=slug).first()
        return _dict(row) if row else None


def list_sessions(user_id: int, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    with _session() as s:
        rows = (
            s.query(SiteSession)
            .filter_by(user_id=user_id)
            .order_by(SiteSession.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [_dict(r) for r in rows]


def count_sessions(user_id: int | None = None, *, active_only: bool = False) -> int:
    """Nombre de sites d'un compte (ou de la plateforme si `user_id` est absent).

    `active_only` exclut les sites archivés : c'est ce compte-là que le quota de
    l'offre limite, un site archivé ne consommant plus de ressources.
    """
    with _session() as s:
        q = s.query(SiteSession)
        if user_id is not None:
            q = q.filter_by(user_id=user_id)
        if active_only:
            q = q.filter(SiteSession.archived_at.is_(None))
        return q.count()


# --------------------------------------------------------------------------- #
# Artefacts
# --------------------------------------------------------------------------- #
def add_artifact(session_id: str, kind: str, version: int, payload: Any) -> int:
    """Enregistre un artefact, en remplaçant celui de même (session, kind, version).

    L'écriture est idempotente parce que plusieurs opérations légitimes réécrivent le
    même triplet : republier une version déjà publiée (retour arrière), ou relancer
    `/api/agents/code` sur une session existante. Avec un INSERT sec, la contrainte
    d'unicité levait une IntegrityError qui ressortait en HTTP 500.

    Le remplacement réinsère une ligne : le nouvel `id` marque l'écriture la plus
    récente, ce dont `latest_artifact` a besoin pour savoir quelle version est en ligne.
    """
    with _session() as s:
        s.query(Artifact).filter_by(session_id=session_id, kind=kind, version=version).delete()
        row = Artifact(
            session_id=session_id,
            kind=kind,
            version=version,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
            created_at=_utcnow(),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return int(row.id)


def latest_artifact(session_id: str, kind: str) -> dict[str, Any] | None:
    """Artefact le plus récemment écrit pour ce type, par ordre d'écriture.

    À distinguer de `get_artifacts`, qui trie par numéro de version : après un retour
    arrière, la dernière publication porte le plus petit numéro de version, pas le plus
    grand.
    """
    with _session() as s:
        row = (
            s.query(Artifact)
            .filter_by(session_id=session_id, kind=kind)
            .order_by(Artifact.id.desc())
            .first()
        )
        return _dict(row) if row else None


def get_artifacts(session_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    with _session() as s:
        q = s.query(Artifact).filter_by(session_id=session_id)
        if kind:
            q = q.filter_by(kind=kind).order_by(Artifact.version)
        else:
            q = q.order_by(Artifact.id)
        return [_dict(r) for r in q.all()]


def latest_version(session_id: str, kind: str) -> int:
    arts = get_artifacts(session_id, kind)
    return max((a["version"] for a in arts), default=0)


# --------------------------------------------------------------------------- #
# Compteurs d'usage (quotas)
# --------------------------------------------------------------------------- #
def increment_usage(user_id: int, metric: str, period: str, amount: int = 1) -> int:
    """Incrémente un compteur et retourne sa nouvelle valeur.

    Passe par un `UPDATE` puis un `INSERT` de repli plutôt qu'un `ON CONFLICT` : le
    code reste lisible et portable, et la course entre deux générations simultanées du
    même compte se solde au pire par un compteur créé deux fois — que la contrainte
    d'unicité rattrape.
    """
    with _session() as s:
        row = s.query(UsageCounter).filter_by(user_id=user_id, period=period, metric=metric).first()
        if row is None:
            row = UsageCounter(user_id=user_id, period=period, metric=metric, count=0)
            s.add(row)
        row.count += amount
        row.updated_at = _utcnow()
        try:
            s.commit()
        except Exception:
            s.rollback()
            return get_usage(user_id, metric, period)
        return int(row.count)


def get_usage(user_id: int, metric: str, period: str) -> int:
    with _session() as s:
        row = s.query(UsageCounter).filter_by(user_id=user_id, period=period, metric=metric).first()
        return int(row.count) if row else 0


def usage_summary(user_id: int, period: str) -> dict[str, int]:
    with _session() as s:
        rows = s.query(UsageCounter).filter_by(user_id=user_id, period=period).all()
        return {r.metric: int(r.count) for r in rows}
