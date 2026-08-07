"""Agrégations du back-office : indicateurs, séries, entonnoirs, cohortes.

Toutes les requêtes du dashboard vivent ici, jamais dans le routeur. Deux raisons :
elles sont testables sans passer par HTTP, et le jour où l'une d'elles devient trop
lente, on sait exactement où poser une vue matérialisée.

Convention de format : chaque fonction renvoie des structures directement
sérialisables, avec les libellés déjà rédigés en français. Le front dessine, il ne
recalcule pas — c'est ce qui garde la logique métier d'un seul côté.

Les séries temporelles sont toujours **complétées** : un jour sans activité apparaît
avec la valeur zéro. Sans cela, une courbe relie le dernier point actif au suivant et
laisse croire à une activité continue là où il n'y avait rien.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func

from app import db
from app.africa import countries, currencies
from app.billing import plans

#: Granularités acceptées, associées à leur unité `date_trunc` PostgreSQL.
GRANULARITIES = {"day": "day", "week": "week", "month": "month"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _since(days: int) -> datetime:
    return _utcnow() - timedelta(days=days)


# --------------------------------------------------------------------------- #
# Vue d'ensemble
# --------------------------------------------------------------------------- #
def overview(days: int = 30) -> dict[str, Any]:
    """Indicateurs de tête, avec la variation par rapport à la période précédente.

    La comparaison à la période précédente est systématique : un nombre seul
    (« 143 sites ») ne dit pas si la situation s'améliore. C'est la variation qui
    déclenche une décision.
    """
    now = _utcnow()
    start = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)

    with db.session_scope() as s:
        users_total = s.query(func.count(db.User.id)).scalar() or 0
        users_new = s.query(func.count(db.User.id)).filter(db.User.created_at >= start).scalar() or 0
        users_prev = (
            s.query(func.count(db.User.id))
            .filter(db.User.created_at >= previous_start, db.User.created_at < start)
            .scalar() or 0
        )
        # Actifs : un compte vu au cours de la période. `last_seen_at` est mis à jour
        # à chaque appel authentifié, ce qui en fait une mesure d'usage réel et non
        # de simple existence.
        actives = (
            s.query(func.count(db.User.id)).filter(db.User.last_seen_at >= start).scalar() or 0
        )
        actives_7d = (
            s.query(func.count(db.User.id))
            .filter(db.User.last_seen_at >= now - timedelta(days=7))
            .scalar() or 0
        )

        sites_total = s.query(func.count(db.SiteSession.id)).scalar() or 0
        sites_new = (
            s.query(func.count(db.SiteSession.id))
            .filter(db.SiteSession.created_at >= start).scalar() or 0
        )
        sites_prev = (
            s.query(func.count(db.SiteSession.id))
            .filter(db.SiteSession.created_at >= previous_start, db.SiteSession.created_at < start)
            .scalar() or 0
        )
        published_total = (
            s.query(func.count(db.SiteSession.id))
            .filter(db.SiteSession.published_at.isnot(None)).scalar() or 0
        )
        published_new = (
            s.query(func.count(db.SiteSession.id))
            .filter(db.SiteSession.published_at >= start).scalar() or 0
        )

        # Coût des modèles : le poste de dépense variable de la plateforme.
        llm = (
            s.query(
                func.count(db.LlmCall.id),
                func.coalesce(func.sum(db.LlmCall.cost_xof), 0.0),
                func.coalesce(func.avg(db.LlmCall.latency_ms), 0),
                func.sum(case((db.LlmCall.ok.is_(False), 1), else_=0)),
            )
            .filter(db.LlmCall.ts >= start)
            .one()
        )
        llm_calls, llm_cost, llm_latency, llm_errors = llm

        mrr = (
            s.query(func.coalesce(func.sum(db.Subscription.amount_xof), 0))
            .filter(db.Subscription.status == "active")
            .scalar() or 0
        )
        paying = (
            s.query(func.count(func.distinct(db.Subscription.user_id)))
            .filter(db.Subscription.status == "active")
            .scalar() or 0
        )

        # Qualité : moyenne des scores de revue sur la période. C'est l'indicateur qui
        # dit si les sites livrés se dégradent, avant que les clients ne le signalent.
        jobs_done = (
            s.query(func.count(db.Job.id))
            .filter(db.Job.status == "done", db.Job.created_at >= start).scalar() or 0
        )
        jobs_failed = (
            s.query(func.count(db.Job.id))
            .filter(db.Job.status == "failed", db.Job.created_at >= start).scalar() or 0
        )

        visits = (
            s.query(
                func.coalesce(func.sum(db.SiteVisit.views), 0),
                func.coalesce(func.sum(db.SiteVisit.whatsapp_clicks), 0),
                func.coalesce(func.sum(db.SiteVisit.call_clicks), 0),
            )
            .filter(db.SiteVisit.day >= start.strftime("%Y-%m-%d"))
            .one()
        )

    total_jobs = jobs_done + jobs_failed
    return {
        "period_days": days,
        "kpis": {
            "users_total": users_total,
            "users_new": users_new,
            "users_new_change": _change(users_new, users_prev),
            "users_active": actives,
            "users_active_7d": actives_7d,
            "sites_total": sites_total,
            "sites_new": sites_new,
            "sites_new_change": _change(sites_new, sites_prev),
            "sites_published": published_total,
            "sites_published_new": published_new,
            "publish_rate": _pct(published_total, sites_total),
            "paying_customers": paying,
            "mrr_xof": int(mrr),
            "mrr_formatted": currencies.format_amount(mrr, "XOF"),
            "arpu_xof": int(mrr / paying) if paying else 0,
            "conversion_rate": _pct(paying, users_total),
            "llm_calls": int(llm_calls or 0),
            "llm_cost_xof": round(float(llm_cost or 0), 2),
            "llm_cost_formatted": currencies.format_amount(llm_cost or 0, "XOF"),
            "llm_avg_latency_ms": int(llm_latency or 0),
            "llm_error_rate": _pct(int(llm_errors or 0), int(llm_calls or 0)),
            "cost_per_site_xof": round(float(llm_cost or 0) / sites_new, 1) if sites_new else 0.0,
            "job_success_rate": _pct(jobs_done, total_jobs),
            "jobs_failed": jobs_failed,
            "site_views": int(visits[0] or 0),
            "whatsapp_clicks": int(visits[1] or 0),
            "call_clicks": int(visits[2] or 0),
        },
    }


def _change(current: int | float, previous: int | float) -> float:
    """Variation en pourcentage entre deux périodes.

    Une progression depuis zéro est rendue par `100.0` et non par l'infini : le
    dashboard doit afficher un nombre, et « +100 % » se comprend là où « +∞ % »
    n'informe personne.
    """
    if not previous:
        return 100.0 if current else 0.0
    return round((current - previous) / previous * 100, 1)


def _pct(part: int | float, whole: int | float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


# --------------------------------------------------------------------------- #
# Séries temporelles
# --------------------------------------------------------------------------- #
#: Métrique → (modèle, colonne de date, agrégat). Une table plutôt qu'une cascade de
#: `if` : ajouter une courbe au dashboard devient une ligne de configuration.
_SERIES = {
    "signups": (db.User, db.User.created_at, func.count(db.User.id)),
    "sites": (db.SiteSession, db.SiteSession.created_at, func.count(db.SiteSession.id)),
    "publishes": (db.SiteSession, db.SiteSession.published_at, func.count(db.SiteSession.id)),
    "llm_cost": (db.LlmCall, db.LlmCall.ts, func.coalesce(func.sum(db.LlmCall.cost_xof), 0.0)),
    "llm_calls": (db.LlmCall, db.LlmCall.ts, func.count(db.LlmCall.id)),
    "revenue": (db.Subscription, db.Subscription.started_at, func.coalesce(func.sum(db.Subscription.amount_xof), 0)),
    "jobs": (db.Job, db.Job.created_at, func.count(db.Job.id)),
}


def timeseries(metric: str, days: int = 30, granularity: str = "day") -> dict[str, Any]:
    """Série d'une métrique sur la période, trous comblés à zéro."""
    if metric not in _SERIES:
        raise ValueError(f"Métrique inconnue : {metric}")
    unit = GRANULARITIES.get(granularity, "day")

    _model, date_col, agg = _SERIES[metric]
    start = _since(days)
    bucket = func.date_trunc(unit, date_col).label("bucket")

    with db.session_scope() as s:
        rows = (
            s.query(bucket, agg)
            .filter(date_col >= start)
            .group_by(bucket)
            .order_by(bucket)
            .all()
        )

    found = {r[0].date().isoformat(): float(r[1] or 0) for r in rows if r[0] is not None}
    points = [
        {"date": day, "value": found.get(day, 0)}
        for day in _buckets(start.date(), _utcnow().date(), unit)
    ]
    total = sum(p["value"] for p in points)
    return {
        "metric": metric,
        "granularity": unit,
        "points": points,
        "total": round(total, 2),
        "average": round(total / len(points), 2) if points else 0,
    }


def _buckets(start: date, end: date, unit: str) -> list[str]:
    """Toutes les dates de la période, à la granularité demandée."""
    out: list[str] = []
    if unit == "month":
        cursor = start.replace(day=1)
        while cursor <= end:
            out.append(cursor.isoformat())
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        return out

    step = timedelta(days=7 if unit == "week" else 1)
    # `date_trunc('week')` de PostgreSQL cale sur le lundi : la série doit s'aligner
    # dessus, sinon aucune clé ne correspond et la courbe reste plate à zéro.
    cursor = start - timedelta(days=start.weekday()) if unit == "week" else start
    while cursor <= end:
        out.append(cursor.isoformat())
        cursor += step
    return out


def multi_series(metrics: list[str], days: int = 30, granularity: str = "day") -> dict[str, Any]:
    """Plusieurs séries alignées sur les mêmes dates, pour un graphique superposé."""
    series = {m: timeseries(m, days, granularity) for m in metrics if m in _SERIES}
    dates = series[metrics[0]]["points"] if series and metrics[0] in series else []
    return {
        "dates": [p["date"] for p in dates],
        "series": {name: [p["value"] for p in data["points"]] for name, data in series.items()},
        "totals": {name: data["total"] for name, data in series.items()},
    }


# --------------------------------------------------------------------------- #
# Répartitions
# --------------------------------------------------------------------------- #
def geography(days: int = 90) -> list[dict[str, Any]]:
    """Activité par pays : comptes, sites, revenu. Trié par revenu décroissant.

    C'est la vue qui pilote l'ouverture de marché : elle montre où les comptes se
    créent, et surtout où ils se transforment en abonnements — les deux ne coïncident
    pas toujours.
    """
    start = _since(days)
    with db.session_scope() as s:
        users = dict(
            s.query(db.User.country, func.count(db.User.id)).group_by(db.User.country).all()
        )
        sites = dict(
            s.query(db.SiteSession.country, func.count(db.SiteSession.id))
            .filter(db.SiteSession.created_at >= start)
            .group_by(db.SiteSession.country).all()
        )
        revenue = dict(
            s.query(db.Subscription.country, func.coalesce(func.sum(db.Subscription.amount_xof), 0))
            .filter(db.Subscription.status == "active")
            .group_by(db.Subscription.country).all()
        )

    out = []
    for code in set(users) | set(sites) | set(revenue):
        country = countries.find(code)
        mrr = int(revenue.get(code, 0))
        out.append({
            "country": code,
            "name": country.name_fr if country else code,
            "flag": country.flag if country else "🏳️",
            "currency": country.currency if country else "XOF",
            "zone": country.economic_zone if country else "",
            "users": int(users.get(code, 0)),
            "sites": int(sites.get(code, 0)),
            "mrr_xof": mrr,
            "mrr_formatted": currencies.format_amount(mrr, "XOF"),
        })
    return sorted(out, key=lambda r: (-r["mrr_xof"], -r["users"]))


def plan_distribution() -> list[dict[str, Any]]:
    """Répartition des comptes par offre, avec le revenu que chacune représente."""
    with db.session_scope() as s:
        counts = dict(s.query(db.User.plan, func.count(db.User.id)).group_by(db.User.plan).all())
        revenue = dict(
            s.query(db.Subscription.plan, func.coalesce(func.sum(db.Subscription.amount_xof), 0))
            .filter(db.Subscription.status == "active")
            .group_by(db.Subscription.plan).all()
        )

    total = sum(counts.values()) or 1
    return [
        {
            "plan": key,
            "name": plan.name,
            "users": int(counts.get(key, 0)),
            "share": _pct(int(counts.get(key, 0)), total),
            "mrr_xof": int(revenue.get(key, 0)),
            "mrr_formatted": currencies.format_amount(int(revenue.get(key, 0)), "XOF"),
        }
        for key, plan in plans.PLANS.items()
    ]


def business_types(days: int = 90, limit: int = 12) -> list[dict[str, Any]]:
    """Secteurs d'activité des sites générés — ce que les clients construisent vraiment.

    Alimente le choix des prochains templates : un secteur qui revient sans avoir de
    template dédié est une opportunité produit directement lisible.
    """
    with db.session_scope() as s:
        rows = (
            s.query(db.SiteSession.business_type, func.count(db.SiteSession.id).label("n"))
            .filter(db.SiteSession.created_at >= _since(days), db.SiteSession.business_type.isnot(None))
            .group_by(db.SiteSession.business_type)
            .order_by(func.count(db.SiteSession.id).desc())
            .limit(limit)
            .all()
        )
    total = sum(int(r[1]) for r in rows) or 1
    return [{"type": r[0], "count": int(r[1]), "share": _pct(int(r[1]), total)} for r in rows]


def status_breakdown() -> list[dict[str, Any]]:
    """Répartition des sites par statut — santé du pipeline en un coup d'œil."""
    labels = {
        "pending": "En attente", "running": "En cours", "ready": "Prêt à publier",
        "deployed": "En ligne", "error": "En erreur", "failed": "Échec",
    }
    with db.session_scope() as s:
        rows = s.query(db.SiteSession.status, func.count(db.SiteSession.id)).group_by(db.SiteSession.status).all()
    total = sum(int(r[1]) for r in rows) or 1
    return [
        {"status": r[0], "label": labels.get(r[0], r[0]), "count": int(r[1]), "share": _pct(int(r[1]), total)}
        for r in sorted(rows, key=lambda r: -int(r[1]))
    ]


# --------------------------------------------------------------------------- #
# Entonnoir et rétention
# --------------------------------------------------------------------------- #
def funnel(days: int = 30) -> list[dict[str, Any]]:
    """Parcours d'activation : inscription → site créé → généré → publié.

    C'est le diagnostic produit le plus dense du dashboard. Une chute entre « créé »
    et « généré » désigne un problème technique ; une chute entre « généré » et
    « publié » désigne un problème de qualité perçue — deux causes qui n'appellent
    pas du tout les mêmes corrections.
    """
    start = _since(days)
    with db.session_scope() as s:
        signed_up = s.query(func.count(db.User.id)).filter(db.User.created_at >= start).scalar() or 0
        cohort = [r[0] for r in s.query(db.User.id).filter(db.User.created_at >= start).all()]
        if not cohort:
            created = generated = published = 0
        else:
            created = (
                s.query(func.count(func.distinct(db.SiteSession.user_id)))
                .filter(db.SiteSession.user_id.in_(cohort)).scalar() or 0
            )
            generated = (
                s.query(func.count(func.distinct(db.SiteSession.user_id)))
                .filter(db.SiteSession.user_id.in_(cohort),
                        db.SiteSession.status.in_(["ready", "deployed"])).scalar() or 0
            )
            published = (
                s.query(func.count(func.distinct(db.SiteSession.user_id)))
                .filter(db.SiteSession.user_id.in_(cohort),
                        db.SiteSession.published_at.isnot(None)).scalar() or 0
            )

    steps = [
        ("Inscription", signed_up),
        ("Premier site créé", created),
        ("Site généré", generated),
        ("Site publié", published),
    ]
    out = []
    for index, (label, count) in enumerate(steps):
        previous = steps[index - 1][1] if index else count
        out.append({
            "step": label,
            "count": count,
            "share_of_start": _pct(count, signed_up),
            "step_conversion": _pct(count, previous),
            "dropped": max(0, previous - count) if index else 0,
        })
    return out


def cohorts(months: int = 6) -> dict[str, Any]:
    """Rétention par cohorte mensuelle d'inscription.

    Mesurée sur l'activité réelle (`last_seen_at`) et non sur l'abonnement : un compte
    qui paie mais ne revient jamais est un désabonnement qui n'a pas encore eu lieu, et
    c'est exactement ce qu'on veut voir venir.
    """
    with db.session_scope() as s:
        rows = (
            s.query(
                func.to_char(func.date_trunc("month", db.User.created_at), "YYYY-MM").label("cohort"),
                func.count(db.User.id),
                func.sum(case((db.User.last_seen_at >= _since(30), 1), else_=0)),
                func.sum(case((db.User.last_seen_at >= _since(90), 1), else_=0)),
            )
            .filter(db.User.created_at >= _since(months * 31))
            .group_by("cohort")
            .order_by("cohort")
            .all()
        )
    return {
        "cohorts": [
            {
                "month": r[0],
                "size": int(r[1]),
                "active_30d": int(r[2] or 0),
                "active_90d": int(r[3] or 0),
                "retention_30d": _pct(int(r[2] or 0), int(r[1])),
                "retention_90d": _pct(int(r[3] or 0), int(r[1])),
            }
            for r in rows
        ]
    }


# --------------------------------------------------------------------------- #
# Agents et qualité
# --------------------------------------------------------------------------- #
def agent_performance(days: int = 30) -> list[dict[str, Any]]:
    """Par agent : volume, latence, taux d'erreur, coût. Le tableau de bord des IA."""
    with db.session_scope() as s:
        rows = (
            s.query(
                db.LlmCall.agent,
                db.LlmCall.model,
                func.count(db.LlmCall.id),
                func.coalesce(func.avg(db.LlmCall.latency_ms), 0),
                func.coalesce(func.max(db.LlmCall.latency_ms), 0),
                func.sum(case((db.LlmCall.ok.is_(False), 1), else_=0)),
                func.coalesce(func.sum(db.LlmCall.cost_xof), 0.0),
                func.coalesce(func.sum(db.LlmCall.input_tokens), 0),
                func.coalesce(func.sum(db.LlmCall.output_tokens), 0),
            )
            .filter(db.LlmCall.ts >= _since(days))
            .group_by(db.LlmCall.agent, db.LlmCall.model)
            .order_by(func.count(db.LlmCall.id).desc())
            .all()
        )
    return [
        {
            "agent": r[0], "model": r[1], "calls": int(r[2]),
            "avg_latency_ms": int(r[3]), "max_latency_ms": int(r[4]),
            "errors": int(r[5] or 0), "error_rate": _pct(int(r[5] or 0), int(r[2])),
            "cost_xof": round(float(r[6]), 2),
            "cost_formatted": currencies.format_amount(r[6], "XOF"),
            "input_tokens": int(r[7]), "output_tokens": int(r[8]),
            "cost_per_call_xof": round(float(r[6]) / int(r[2]), 2) if r[2] else 0,
        }
        for r in rows
    ]


def quality_scores(days: int = 30) -> dict[str, Any]:
    """Distribution des scores de revue et verdicts, sur les rapports de la période.

    Les rapports sont stockés en JSON dans `artifacts` : on les relit côté Python
    plutôt que d'interroger le JSON en SQL. Le volume concerné (quelques milliers de
    lignes par mois) ne justifie pas encore une colonne dédiée ; le jour où ce sera le
    cas, seule cette fonction changera.
    """
    with db.session_scope() as s:
        rows = (
            s.query(db.Artifact.payload)
            .filter(db.Artifact.kind == "report", db.Artifact.created_at >= _since(days))
            .all()
        )

    import json

    buckets = {"90-100": 0, "75-89": 0, "60-74": 0, "40-59": 0, "0-39": 0}
    verdicts = {"pass": 0, "warn": 0, "fail": 0}
    severities = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    scores: list[int] = []

    for (raw,) in rows:
        try:
            report = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if not isinstance(report, dict):
            continue
        score = int(report.get("score") or 0)
        scores.append(score)
        buckets[_score_bucket(score)] += 1
        verdict = report.get("verdict")
        if verdict in verdicts:
            verdicts[verdict] += 1
        for finding in report.get("findings") or []:
            sev = (finding or {}).get("severity")
            if sev in severities:
                severities[sev] += 1

    return {
        "reports": len(scores),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "distribution": [{"range": k, "count": v} for k, v in buckets.items()],
        "verdicts": [{"verdict": k, "count": v} for k, v in verdicts.items()],
        "findings_by_severity": [{"severity": k, "count": v} for k, v in severities.items()],
    }


def _score_bucket(score: int) -> str:
    if score >= 90:
        return "90-100"
    if score >= 75:
        return "75-89"
    if score >= 60:
        return "60-74"
    if score >= 40:
        return "40-59"
    return "0-39"


# --------------------------------------------------------------------------- #
# Trafic des sites publiés
# --------------------------------------------------------------------------- #
def traffic(days: int = 30) -> dict[str, Any]:
    """Fréquentation consolidée des sites publiés et taux de contact.

    Le « taux de contact » — clics WhatsApp et appels rapportés aux vues — est
    l'indicateur qui prouve la valeur du produit à un commerçant. Le temps passé sur
    la page ne l'intéresse pas ; savoir que douze personnes l'ont appelé ce mois-ci,
    si.
    """
    start = _since(days).strftime("%Y-%m-%d")
    with db.session_scope() as s:
        daily = (
            s.query(
                db.SiteVisit.day,
                func.sum(db.SiteVisit.views),
                func.sum(db.SiteVisit.visitors),
                func.sum(db.SiteVisit.whatsapp_clicks),
                func.sum(db.SiteVisit.call_clicks),
            )
            .filter(db.SiteVisit.day >= start)
            .group_by(db.SiteVisit.day)
            .order_by(db.SiteVisit.day)
            .all()
        )
        top = (
            s.query(
                db.SiteSession.slug,
                db.SiteSession.country,
                func.sum(db.SiteVisit.views).label("views"),
                func.sum(db.SiteVisit.whatsapp_clicks),
            )
            .join(db.SiteVisit, db.SiteVisit.session_id == db.SiteSession.id)
            .filter(db.SiteVisit.day >= start)
            .group_by(db.SiteSession.slug, db.SiteSession.country)
            .order_by(func.sum(db.SiteVisit.views).desc())
            .limit(10)
            .all()
        )

    views = sum(int(r[1] or 0) for r in daily)
    contacts = sum(int(r[3] or 0) + int(r[4] or 0) for r in daily)
    return {
        "points": [
            {"date": r[0], "views": int(r[1] or 0), "visitors": int(r[2] or 0),
             "whatsapp": int(r[3] or 0), "calls": int(r[4] or 0)}
            for r in daily
        ],
        "total_views": views,
        "total_contacts": contacts,
        "contact_rate": _pct(contacts, views),
        "top_sites": [
            {"slug": r[0], "country": r[1], "views": int(r[2] or 0), "whatsapp": int(r[3] or 0)}
            for r in top
        ],
    }


# --------------------------------------------------------------------------- #
# Activité récente
# --------------------------------------------------------------------------- #
def recent_activity(limit: int = 25) -> list[dict[str, Any]]:
    """Derniers événements produit, mis en forme pour un fil d'activité."""
    labels = {
        "user.signup": "Nouvelle inscription",
        "user.login": "Connexion",
        "site.created": "Site créé",
        "site.generated": "Site généré",
        "site.edited": "Site modifié",
        "site.published": "Site publié",
        "job.failed": "Travail en échec",
        "billing.plan_changed": "Changement d'offre",
        "billing.quota_hit": "Quota atteint",
        "chat.message": "Message de cadrage",
    }
    with db.session_scope() as s:
        rows = (
            s.query(db.Event, db.User.email)
            .outerjoin(db.User, db.User.id == db.Event.user_id)
            .order_by(db.Event.ts.desc())
            .limit(limit)
            .all()
        )
    return [
        {
            **db._dict(event),
            "label": labels.get(event.name, event.name),
            "user_email": email,
        }
        for event, email in rows
    ]


def top_users(days: int = 30, limit: int = 10) -> list[dict[str, Any]]:
    """Comptes les plus actifs — ceux à interroger avant toute décision produit."""
    with db.session_scope() as s:
        rows = (
            s.query(
                db.User.id, db.User.email, db.User.name, db.User.plan, db.User.country,
                func.count(db.SiteSession.id).label("sites"),
            )
            .join(db.SiteSession, db.SiteSession.user_id == db.User.id)
            .filter(db.SiteSession.created_at >= _since(days))
            .group_by(db.User.id, db.User.email, db.User.name, db.User.plan, db.User.country)
            .order_by(func.count(db.SiteSession.id).desc())
            .limit(limit)
            .all()
        )
    return [
        {
            "id": r[0], "email": r[1], "name": r[2], "plan": r[3],
            "country": r[4], "flag": countries.get(r[4]).flag, "sites": int(r[5]),
        }
        for r in rows
    ]
