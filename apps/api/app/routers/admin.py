"""Back-office : pilotage, analytics et administration de la plateforme.

Deux niveaux d'accès, appliqués par dépendance et non par convention :

- `CurrentStaff` — support, admin, owner : **lecture** de tout le back-office.
- `CurrentAdmin` — admin, owner : **écriture** (changement d'offre, suspension,
  interrupteurs, relance de travaux).

Le support consulte le compte d'un client pour l'aider ; il ne le modifie pas. Cette
séparation évite la situation classique où « accès au back-office » finit par
signifier « peut tout faire », y compris pour un stagiaire embauché pour répondre aux
messages WhatsApp.

Toute écriture passe par `events.audit()` **avant** d'être appliquée : une trace
impossible à écrire empêche l'action plutôt que de la laisser passer anonymement.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func

from app import db
from app.africa import countries
from app.analytics import events, queries
from app.billing import plans
from app.config import settings
from app.contracts import (
    AdminJobRow,
    AdminSiteRow,
    AdminUserRow,
    AdminUserUpdate,
    AuditEntry,
    FeatureFlagRow,
    FeatureFlagUpdate,
    SystemHealth,
)
from app.core.pagination import Page, PageParams, page_params
from app.jobs import queue
from app.security import CurrentAdmin, CurrentStaff

logger = logging.getLogger("app.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

Params = Annotated[PageParams, Depends(page_params)]

#: Fenêtres d'analyse proposées. Bornées pour éviter qu'un `?days=100000` ne balaie
#: toute la base sur un écran dont personne n'attend un historique complet.
MAX_DAYS = 365


def _days(days: int) -> int:
    return max(1, min(days, MAX_DAYS))


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "?")


# --------------------------------------------------------------------------- #
# Vue d'ensemble et analytics
# --------------------------------------------------------------------------- #
@router.get("/overview")
def overview(staff: CurrentStaff, days: int = Query(30, ge=1, le=MAX_DAYS)) -> dict[str, Any]:
    """Indicateurs de tête, entonnoir, répartitions et activité récente en un appel.

    Regroupé volontairement : c'est l'écran d'accueil du back-office, et le charger en
    huit requêtes parallèles depuis un navigateur en 3G donnerait huit occasions
    d'échouer à moitié. Une réponse, un état cohérent.
    """
    window = _days(days)
    return {
        **queries.overview(window),
        "funnel": queries.funnel(window),
        "plans": queries.plan_distribution(),
        "statuses": queries.status_breakdown(),
        "geography": queries.geography(window)[:8],
        "recent": queries.recent_activity(12),
        "queue": queue.stats(),
    }


@router.get("/timeseries")
def timeseries(
    staff: CurrentStaff,
    metric: str = Query("sites", description="signups | sites | publishes | llm_cost | llm_calls | revenue | jobs"),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
) -> dict[str, Any]:
    try:
        return queries.timeseries(metric, _days(days), granularity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/timeseries/multi")
def multi_timeseries(
    staff: CurrentStaff,
    metrics: str = Query("signups,sites,publishes"),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
) -> dict[str, Any]:
    """Plusieurs séries alignées sur les mêmes dates, pour un graphique superposé."""
    wanted = [m.strip() for m in metrics.split(",") if m.strip()]
    if not wanted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune métrique demandée.")
    return queries.multi_series(wanted, _days(days), granularity)


@router.get("/analytics/geography")
def geography(staff: CurrentStaff, days: int = Query(90, ge=1, le=MAX_DAYS)) -> list[dict[str, Any]]:
    return queries.geography(_days(days))


@router.get("/analytics/funnel")
def funnel(staff: CurrentStaff, days: int = Query(30, ge=1, le=MAX_DAYS)) -> list[dict[str, Any]]:
    return queries.funnel(_days(days))


@router.get("/analytics/cohorts")
def cohorts(staff: CurrentStaff, months: int = Query(6, ge=1, le=24)) -> dict[str, Any]:
    return queries.cohorts(months)


@router.get("/analytics/business-types")
def business_types(staff: CurrentStaff, days: int = Query(90, ge=1, le=MAX_DAYS)) -> list[dict[str, Any]]:
    return queries.business_types(_days(days))


@router.get("/analytics/traffic")
def traffic(staff: CurrentStaff, days: int = Query(30, ge=1, le=MAX_DAYS)) -> dict[str, Any]:
    """Fréquentation des sites publiés et taux de contact (WhatsApp, appels)."""
    return queries.traffic(_days(days))


@router.get("/analytics/quality")
def quality(staff: CurrentStaff, days: int = Query(30, ge=1, le=MAX_DAYS)) -> dict[str, Any]:
    """Distribution des scores de revue et findings par gravité."""
    return queries.quality_scores(_days(days))


@router.get("/analytics/agents")
def agent_performance(staff: CurrentStaff, days: int = Query(30, ge=1, le=MAX_DAYS)) -> list[dict[str, Any]]:
    """Volume, latence, taux d'erreur et coût, par agent et par modèle."""
    return queries.agent_performance(_days(days))


@router.get("/analytics/top-users")
def top_users(staff: CurrentStaff, days: int = Query(30, ge=1, le=MAX_DAYS)) -> list[dict[str, Any]]:
    return queries.top_users(_days(days))


@router.get("/activity")
def activity(staff: CurrentStaff, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return queries.recent_activity(limit)


# --------------------------------------------------------------------------- #
# Comptes
# --------------------------------------------------------------------------- #
@router.get("/users", response_model=Page[AdminUserRow])
def list_users(
    staff: CurrentStaff,
    params: Params,
    q: str | None = Query(None, description="Recherche sur e-mail, nom ou société."),
    role: str | None = None,
    plan: str | None = None,
    country: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    sort: str = Query("created_at", pattern="^(created_at|last_seen_at|email|sites)$"),
) -> Page[AdminUserRow]:
    """Liste des comptes, filtrable et paginée.

    Le nombre de sites par compte est obtenu par une sous-requête agrégée et non par
    une boucle : avec mille comptes affichés vingt-cinq par page, la version naïve
    exécuterait vingt-cinq requêtes de plus à chaque chargement.
    """
    with db.session_scope() as s:
        sites_sub = (
            s.query(
                db.SiteSession.user_id.label("uid"),
                func.count(db.SiteSession.id).label("sites"),
                func.sum(func.cast(db.SiteSession.published_at.isnot(None), db.Integer)).label("published"),
            )
            .group_by(db.SiteSession.user_id)
            .subquery()
        )

        base = s.query(db.User, sites_sub.c.sites, sites_sub.c.published).outerjoin(
            sites_sub, sites_sub.c.uid == db.User.id
        )

        if q:
            pattern = f"%{q.strip().lower()}%"
            base = base.filter(
                func.lower(db.User.email).like(pattern)
                | func.lower(func.coalesce(db.User.name, "")).like(pattern)
                | func.lower(func.coalesce(db.User.company, "")).like(pattern)
            )
        if role:
            base = base.filter(db.User.role == role)
        if plan:
            base = base.filter(db.User.plan == plan)
        if country:
            base = base.filter(db.User.country == country.upper())
        if status_filter:
            base = base.filter(db.User.status == status_filter)

        total = base.count()

        order = {
            "created_at": db.User.created_at.desc(),
            "last_seen_at": db.User.last_seen_at.desc().nullslast(),
            "email": db.User.email.asc(),
            "sites": sites_sub.c.sites.desc().nullslast(),
        }[sort]
        rows = base.order_by(order).limit(params.limit).offset(params.offset).all()

        items = []
        for user, sites, published in rows:
            data = db._dict(user)
            country_obj = countries.find(data["country"])
            items.append(
                AdminUserRow(
                    id=data["id"], email=data["email"], name=data.get("name"),
                    role=data["role"], plan=data["plan"], status=data["status"],
                    provider=data["provider"], country=data["country"],
                    country_name=country_obj.name_fr if country_obj else data["country"],
                    flag=country_obj.flag if country_obj else "🏳️",
                    company=data.get("company"), phone=data.get("phone"),
                    sites=int(sites or 0), published=int(published or 0),
                    created_at=data["created_at"], last_seen_at=data.get("last_seen_at"),
                )
            )

    return Page.build(items, total, params)


@router.get("/users/{user_id}")
def get_user_detail(user_id: int, staff: CurrentStaff) -> dict[str, Any]:
    """Fiche complète d'un compte : profil, consommation, sites, abonnements."""
    user = db.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")

    from app.billing import quotas as quota_mod

    period = quota_mod.current_period()
    plan = plans.get(user["plan"])
    country = countries.get(user["country"])

    with db.session_scope() as s:
        sites = (
            s.query(db.SiteSession)
            .filter_by(user_id=user_id)
            .order_by(db.SiteSession.created_at.desc())
            .limit(50)
            .all()
        )
        subs = (
            s.query(db.Subscription)
            .filter_by(user_id=user_id)
            .order_by(db.Subscription.started_at.desc())
            .limit(12)
            .all()
        )
        llm_cost = (
            s.query(func.coalesce(func.sum(db.LlmCall.cost_xof), 0.0))
            .filter(db.LlmCall.user_id == user_id)
            .scalar()
        )

    # Le mot de passe n'est jamais exposé, même haché : le back-office n'en a aucun
    # usage, et ce qui ne transite pas ne fuite pas.
    profile = {k: v for k, v in user.items() if k != "password_hash"}
    return {
        "user": profile,
        "country": {"code": country.code, "name": country.name_fr, "flag": country.flag,
                    "currency": country.currency, "dial_code": country.dial_code},
        "plan": {"key": plan.key, "name": plan.name, "quotas": plans.quotas_public(plan.key),
                 "price": plans.price_for(plan.key, user["country"])},
        "usage": db.usage_summary(user_id, period),
        "period": period,
        "lifetime_llm_cost_xof": round(float(llm_cost or 0), 2),
        "sites": [db._dict(row) for row in sites],
        "subscriptions": [db._dict(row) for row in subs],
    }


@router.patch("/users/{user_id}", response_model=AdminUserRow)
def update_user(
    user_id: int, payload: AdminUserUpdate, admin: CurrentAdmin, request: Request
) -> AdminUserRow:
    """Modifie un compte. Toute modification est auditée avant d'être appliquée."""
    user = db.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")

    updates = payload.model_dump(exclude_none=True, exclude={"note"})
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune modification demandée.")

    if "plan" in updates and updates["plan"] not in plans.PLANS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Offre inconnue : {updates['plan']}.")
    if "country" in updates:
        code = updates["country"].upper()
        if countries.find(code) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Pays non desservi : {code}.")
        updates["country"] = code

    # Un administrateur ne se retire pas lui-même ses droits par mégarde, et ne se
    # suspend pas non plus : ce sont les deux gestes qui ferment la porte de
    # l'intérieur, sans personne pour la rouvrir.
    if user_id == admin["id"] and (updates.get("role") or updates.get("status") == "suspended"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas modifier votre propre rôle ni vous suspendre.",
        )

    if updates.get("status") == "suspended":
        from datetime import datetime, timezone

        updates["suspended_at"] = datetime.now(timezone.utc)
        updates["suspension_reason"] = payload.note or "Compte suspendu par l'administration."
    elif updates.get("status") == "active":
        updates["suspended_at"] = None
        updates["suspension_reason"] = None

    changes = {k: {"avant": user.get(k), "après": v} for k, v in updates.items() if user.get(k) != v}
    events.audit(
        "user.update", actor=admin, target_type="user", target_id=user_id,
        changes=changes, ip=_client_ip(request), note=payload.note,
    )

    updated = db.update_user(user_id, **updates)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")

    if "plan" in updates:
        events.track(
            events.PLAN_CHANGED, user_id=user_id, country=updated["country"],
            props={"from": user["plan"], "to": updates["plan"], "by": "admin"},
        )

    country_obj = countries.get(updated["country"])
    return AdminUserRow(
        id=updated["id"], email=updated["email"], name=updated.get("name"),
        role=updated["role"], plan=updated["plan"], status=updated["status"],
        provider=updated["provider"], country=updated["country"],
        country_name=country_obj.name_fr, flag=country_obj.flag,
        company=updated.get("company"), phone=updated.get("phone"),
        sites=db.count_sessions(user_id), created_at=updated["created_at"],
        last_seen_at=updated.get("last_seen_at"),
    )


# --------------------------------------------------------------------------- #
# Sites
# --------------------------------------------------------------------------- #
@router.get("/sites", response_model=Page[AdminSiteRow])
def list_sites(
    staff: CurrentStaff,
    params: Params,
    q: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    country: str | None = None,
) -> Page[AdminSiteRow]:
    """Tous les sites de la plateforme, filtrables et paginés."""
    with db.session_scope() as s:
        views_sub = (
            s.query(
                db.SiteVisit.session_id.label("sid"),
                func.sum(db.SiteVisit.views).label("views"),
            )
            .group_by(db.SiteVisit.session_id)
            .subquery()
        )
        base = (
            s.query(db.SiteSession, db.User.email, views_sub.c.views)
            .outerjoin(db.User, db.User.id == db.SiteSession.user_id)
            .outerjoin(views_sub, views_sub.c.sid == db.SiteSession.id)
        )
        if q:
            pattern = f"%{q.strip().lower()}%"
            base = base.filter(
                func.lower(db.SiteSession.slug).like(pattern)
                | func.lower(db.SiteSession.prompt).like(pattern)
            )
        if status_filter:
            base = base.filter(db.SiteSession.status == status_filter)
        if country:
            base = base.filter(db.SiteSession.country == country.upper())

        total = base.count()
        rows = base.order_by(db.SiteSession.created_at.desc()).limit(params.limit).offset(params.offset).all()

        items = []
        for session, email, views in rows:
            data = db._dict(session)
            report = _last_report(s, data["id"])
            items.append(
                AdminSiteRow(
                    id=data["id"], slug=data["slug"], user_id=data["user_id"], user_email=email,
                    status=data["status"], country=data["country"],
                    flag=countries.get(data["country"]).flag,
                    business_type=data.get("business_type"),
                    versions=_version_count(s, data["id"]),
                    score=report.get("score") if report else None,
                    verdict=report.get("verdict") if report else None,
                    site_url=data.get("site_url"), views=int(views or 0),
                    created_at=data["created_at"], published_at=data.get("published_at"),
                )
            )

    return Page.build(items, total, params)


def _version_count(session, session_id: str) -> int:
    return (
        session.query(func.count(db.Artifact.id))
        .filter(db.Artifact.session_id == session_id, db.Artifact.kind == "site")
        .scalar() or 0
    )


def _last_report(session, session_id: str) -> dict | None:
    """Dernier rapport de revue d'une session, décodé. `None` s'il est illisible."""
    import json

    row = (
        session.query(db.Artifact.payload)
        .filter(db.Artifact.session_id == session_id, db.Artifact.kind == "report")
        .order_by(db.Artifact.id.desc())
        .first()
    )
    if row is None:
        return None
    try:
        payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


# --------------------------------------------------------------------------- #
# File de travaux
# --------------------------------------------------------------------------- #
@router.get("/jobs", response_model=Page[AdminJobRow])
def list_jobs(
    staff: CurrentStaff,
    params: Params,
    status_filter: str | None = Query(None, alias="status"),
    kind: str | None = None,
) -> Page[AdminJobRow]:
    rows, total = queue.list_jobs(status=status_filter, kind=kind, limit=params.limit, offset=params.offset)
    return Page.build([AdminJobRow(**r) for r in rows], total, params)


@router.get("/jobs/stats")
def job_stats(staff: CurrentStaff) -> dict[str, Any]:
    return queue.stats()


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, admin: CurrentAdmin, request: Request) -> dict[str, Any]:
    """Relance un travail en échec après correction de sa cause."""
    events.audit("job.retry", actor=admin, target_type="job", target_id=job_id, ip=_client_ip(request))
    if not queue.retry(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travail introuvable ou déjà en file.",
        )
    return {"ok": True, "job_id": job_id}


@router.post("/jobs/reclaim")
def reclaim_jobs(admin: CurrentAdmin, request: Request) -> dict[str, Any]:
    """Reprend les travaux dont le worker a disparu, sans attendre l'entretien."""
    events.audit("job.reclaim", actor=admin, target_type="queue", ip=_client_ip(request))
    return {"reclaimed": queue.reclaim_stale()}


# --------------------------------------------------------------------------- #
# Journal d'audit
# --------------------------------------------------------------------------- #
@router.get("/audit", response_model=Page[AuditEntry])
def audit_log(
    staff: CurrentStaff,
    params: Params,
    action: str | None = None,
    actor_id: int | None = None,
) -> Page[AuditEntry]:
    with db.session_scope() as s:
        base = s.query(db.AuditLog)
        if action:
            base = base.filter(db.AuditLog.action == action)
        if actor_id:
            base = base.filter(db.AuditLog.actor_id == actor_id)
        total = base.count()
        rows = base.order_by(db.AuditLog.ts.desc()).limit(params.limit).offset(params.offset).all()
        items = [AuditEntry(**db._dict(r)) for r in rows]
    return Page.build(items, total, params)


# --------------------------------------------------------------------------- #
# Interrupteurs de fonctionnalité
# --------------------------------------------------------------------------- #
@router.get("/flags", response_model=list[FeatureFlagRow])
def list_flags(staff: CurrentStaff) -> list[FeatureFlagRow]:
    return [FeatureFlagRow(**f) for f in events.list_flags()]


@router.put("/flags/{key}", response_model=FeatureFlagRow)
def set_flag(key: str, payload: FeatureFlagUpdate, admin: CurrentAdmin, request: Request) -> FeatureFlagRow:
    events.audit(
        "flag.set", actor=admin, target_type="flag", target_id=key,
        changes=payload.model_dump(), ip=_client_ip(request),
    )
    flag = events.set_flag(
        key,
        enabled=payload.enabled,
        rollout_percent=payload.rollout_percent,
        description=payload.description,
        actor_email=admin["email"],
    )
    return FeatureFlagRow(**flag)


# --------------------------------------------------------------------------- #
# Système
# --------------------------------------------------------------------------- #
@router.get("/system", response_model=SystemHealth)
def system_health(staff: CurrentStaff) -> SystemHealth:
    """État d'exploitation : base, file, intégrations, anomalies de configuration.

    Les avertissements viennent de `settings.validate()`, c'est-à-dire exactement des
    mêmes contrôles qu'au démarrage. Les afficher ici permet de constater qu'une
    configuration a dérivé sans avoir à ouvrir les journaux du serveur.
    """
    database_ok = True
    try:
        with db.session_scope() as s:
            s.query(func.count(db.User.id)).scalar()
    except Exception:
        logger.exception("Sonde base de données en échec")
        database_ok = False

    try:
        queue_stats = queue.stats()
    except Exception:
        queue_stats = {}

    warnings = settings.validate()
    critical = [w for w in warnings if w.startswith("CRITIQUE")]
    # « Dégradé » et non « en panne » tant que la base répond : la plateforme sert
    # encore les sites publiés et les pages existantes, ce qui n'est pas rien.
    state = "down" if not database_ok else ("degraded" if critical or queue_stats.get("failed", 0) > 10 else "ok")

    return SystemHealth(
        status=state,
        database=database_ok,
        queue=queue_stats,
        llm_configured=bool(settings.gemini_api_keys) or settings.gemini_mock,
        payments_configured=settings.payments_configured,
        vps_configured=settings.vps_configured,
        job_mode=settings.job_mode,
        environment=settings.env,
        version=settings.public_base_url,
        warnings=warnings,
    )


@router.get("/config")
def config_summary(admin: CurrentAdmin) -> dict[str, Any]:
    """Configuration effective, **sans aucun secret**.

    Réservé aux administrateurs et non au support : même expurgée, cette vue décrit
    la topologie du service. On y publie des booléens « configuré / pas configuré »
    plutôt que des valeurs — savoir qu'une clé existe suffit au diagnostic, la
    connaître ne sert qu'à en abuser.
    """
    return {
        "environment": settings.env,
        "job_mode": settings.job_mode,
        "job_concurrency": settings.job_concurrency,
        "default_country": settings.default_country,
        "default_currency": settings.default_currency,
        "enabled_countries": settings.enabled_countries or [c.code for c in countries.list_countries()],
        "public_base_url": settings.public_base_url,
        "app_base_url": settings.app_base_url,
        "cors_origins": settings.cors_origins,
        "models": {
            "coder": settings.gemini_coder_model,
            "reviewer": settings.gemini_reviewer_model,
            "mock": settings.gemini_mock,
            "keys_configured": len(settings.gemini_api_keys),
        },
        "integrations": {
            "google_oauth": settings.google_oauth_configured,
            "github_oauth": settings.github_oauth_configured,
            "n8n_designer": bool(settings.n8n_designer_url),
            "payments": settings.payments_configured,
            "payment_provider": settings.payment_provider or None,
            "vps": settings.vps_configured,
        },
        "llm_pricing_xof_per_mtok": {
            "input": settings.llm_cost_per_mtok_in_xof,
            "output": settings.llm_cost_per_mtok_out_xof,
        },
        "warnings": settings.validate(),
    }
