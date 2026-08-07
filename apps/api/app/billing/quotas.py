"""Application des quotas d'abonnement.

Le contrôle vit ici, et pas dans les routeurs, pour une raison précise : un quota
appliqué à un seul endroit finit toujours par être contourné par un autre chemin.
La génération est joignable depuis `/api/dev/generate`, depuis `/api/sessions/{id}/edit`
et depuis les endpoints `/api/agents/*` pilotés par n8n. Un `if` recopié trois fois
diverge à la première évolution.

Chaque contrôle renvoie une `QuotaCheck` plutôt que de lever : l'appelant décide s'il
refuse (402) ou s'il se contente d'avertir. Le message est rédigé pour l'utilisateur
final, pas pour les journaux — c'est celui qu'il lira avant de décider de payer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.billing import plans

UNLIMITED = -1


@dataclass(frozen=True)
class QuotaCheck:
    """Résultat d'un contrôle de quota."""

    allowed: bool
    limit: int
    used: int
    resource: str
    message: str = ""
    upgrade_to: str | None = None

    @property
    def remaining(self) -> int:
        if self.limit == UNLIMITED:
            return UNLIMITED
        return max(0, self.limit - self.used)

    def raise_if_denied(self) -> None:
        """Transforme un refus en 402, avec de quoi proposer la montée en gamme.

        402 Payment Required plutôt que 403 : le compte a bien le droit d'effectuer
        l'action, c'est son forfait qui ne le couvre pas. La nuance permet au front
        d'ouvrir la page d'abonnement au lieu d'afficher « accès refusé ».
        """
        if self.allowed:
            return
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": self.message,
                "resource": self.resource,
                "limit": self.limit,
                "used": self.used,
                "upgrade_to": self.upgrade_to,
            },
        )


def _next_plan(current: str) -> str | None:
    """Offre immédiatement supérieure, pour orienter la proposition commerciale."""
    keys = list(plans.PLANS)
    try:
        index = keys.index(plans.get(current).key)
    except ValueError:
        return None
    return keys[index + 1] if index + 1 < len(keys) else None


def _check(resource: str, used: int, limit: int, plan_key: str, message: str) -> QuotaCheck:
    if limit == UNLIMITED:
        return QuotaCheck(True, UNLIMITED, used, resource)
    return QuotaCheck(
        allowed=used < limit,
        limit=limit,
        used=used,
        resource=resource,
        message=message,
        upgrade_to=_next_plan(plan_key),
    )


def check_sites(plan_key: str, current_sites: int) -> QuotaCheck:
    plan = plans.get(plan_key)
    return _check(
        "sites", current_sites, plan.quotas.sites, plan.key,
        f"Votre offre {plan.name} permet {plan.quotas.sites} site(s). "
        "Passez à l'offre supérieure ou supprimez un site existant pour en créer un nouveau.",
    )


def check_generations(plan_key: str, used_this_month: int) -> QuotaCheck:
    plan = plans.get(plan_key)
    return _check(
        "generations", used_this_month, plan.quotas.generations_per_month, plan.key,
        f"Vous avez utilisé vos {plan.quotas.generations_per_month} générations du mois "
        f"(offre {plan.name}). Le compteur repart le 1er du mois prochain.",
    )


def check_versions(plan_key: str, versions_on_site: int) -> QuotaCheck:
    plan = plans.get(plan_key)
    return _check(
        "versions", versions_on_site, plan.quotas.versions_per_site, plan.key,
        f"Ce site a atteint ses {plan.quotas.versions_per_site} versions conservées "
        f"(offre {plan.name}).",
    )


def check_seats(plan_key: str, members: int) -> QuotaCheck:
    plan = plans.get(plan_key)
    return _check(
        "seats", members, plan.quotas.team_seats, plan.key,
        f"Votre offre {plan.name} permet {plan.quotas.team_seats} collaborateur(s).",
    )


def require_feature(plan_key: str, feature: str) -> None:
    """Refuse l'accès à une fonctionnalité absente du forfait.

    Args:
        feature: nom d'un booléen de `Quotas` (`custom_domain`, `api_access`…).
    """
    plan = plans.get(plan_key)
    if getattr(plan.quotas, feature, False):
        return
    labels = {
        "custom_domain": "Le nom de domaine personnalisé",
        "remove_branding": "Le retrait de la mention Jarvis",
        "api_access": "L'accès API",
        "analytics": "Les statistiques de fréquentation",
        "seo_tools": "Les outils SEO",
        "export_code": "L'export du code source",
        "white_label": "La marque blanche",
        "priority_queue": "La file de génération prioritaire",
    }
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "message": f"{labels.get(feature, feature)} n'est pas inclus dans l'offre {plan.name}.",
            "resource": feature,
            "upgrade_to": _next_plan(plan.key),
        },
    )


def current_period() -> str:
    """Période de facturation en cours, au format `AAAA-MM`.

    Les compteurs mensuels sont indexés dessus plutôt que sur une fenêtre glissante :
    « vos générations repartent le 1er » est une règle qu'un utilisateur comprend
    sans explication, contrairement à « dans 6 jours et 4 heures ».
    """
    return datetime.now(timezone.utc).strftime("%Y-%m")


def queue_priority(plan_key: str) -> int:
    """Priorité dans la file de génération. Plus le nombre est bas, plus c'est tôt.

    Les offres payantes passent devant : c'est la contrepartie concrète et immédiate
    de l'abonnement, celle qui se ressent dès la première utilisation aux heures de
    pointe.
    """
    plan = plans.get(plan_key)
    if plan.quotas.white_label:
        return 0
    if plan.quotas.priority_queue:
        return 1
    if plan.monthly_xof > 0:
        return 2
    return 3
