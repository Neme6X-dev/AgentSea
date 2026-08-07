"""Compte du client : offre, consommation, tarification localisée.

Distinct du back-office : ici, un utilisateur consulte **son** compte. Aucune de ces
routes n'accepte d'identifiant de compte en paramètre — le compte est toujours celui
du porteur du jeton. C'est ce qui rend impossible l'accès à la consommation d'un
voisin en changeant un chiffre dans l'URL.
"""
from __future__ import annotations

from fastapi import APIRouter

from app import db
from app.africa import countries, currencies, locales, payments
from app.billing import plans, quotas
from app.contracts import AccountOverview, PlanOffer, QuotaUsage, UserPublic
from app.security import CurrentUser

router = APIRouter(prefix="/api/account", tags=["account"])

#: Libellés des ressources suivies. Rédigés côté serveur pour que le front n'ait pas à
#: maintenir sa propre table de traduction des noms de quotas.
RESOURCE_LABELS = {
    "generations": "Générations ce mois-ci",
    "sites": "Sites actifs",
    "seats": "Collaborateurs",
}


@router.get("", response_model=AccountOverview)
def account_overview(user: CurrentUser) -> AccountOverview:
    """Offre, quotas, consommation et contexte régional du compte."""
    plan = plans.get(user["plan"])
    period = quotas.current_period()
    usage_counts = db.usage_summary(user["id"], period)
    sites = db.count_sessions(user["id"], active_only=True)
    published = sum(1 for s in db.list_sessions(user["id"], limit=500) if s.get("published_at"))
    country = countries.get(user["country"])

    usage = [
        _usage_row("generations", usage_counts.get("generations", 0), plan.quotas.generations_per_month),
        _usage_row("sites", sites, plan.quotas.sites),
        _usage_row("seats", 1, plan.quotas.team_seats),
    ]

    return AccountOverview(
        user=UserPublic.from_row(user),
        plan=plan.key,
        plan_name=plan.name,
        period=period,
        quotas=plans.quotas_public(plan.key),
        usage=usage,
        sites_count=sites,
        published_count=published,
        country_profile={
            "code": country.code,
            "name": country.name_fr,
            "flag": country.flag,
            "currency": country.currency,
            "currency_symbol": currencies.get(country.currency).symbol,
            "dial_code": country.dial_code,
            "timezone": country.timezone,
            "languages": list(country.languages),
            "mobile_money": list(country.mobile_money),
            "payment_methods": countries.payment_methods(country.code),
            "business_hours_hint": locales.business_hours_hint(country.code),
            "address_hint": locales.address_hint(country.code),
        },
    )


def _usage_row(resource: str, used: int, limit: int) -> QuotaUsage:
    return QuotaUsage(
        resource=resource,
        label=RESOURCE_LABELS.get(resource, resource),
        used=used,
        limit=limit,
        # Une limite illimitée donne un pourcentage nul : le front dessine alors le
        # mot « illimité » au lieu d'une jauge, qui n'aurait aucun sens.
        percent=round(min(100.0, used / limit * 100), 1) if limit > 0 else 0.0,
    )


@router.get("/plans", response_model=list[PlanOffer])
def plan_catalog(user: CurrentUser, country: str | None = None) -> list[PlanOffer]:
    """Grille tarifaire, libellée dans la devise du pays du compte.

    Le pays peut être forcé en paramètre pour prévisualiser une autre grille — ce que
    fait l'équipe commerciale avant d'ouvrir un marché.
    """
    code = (country or user.get("country") or "BJ").upper()
    return [PlanOffer(**offer) for offer in plans.catalog(code)]


@router.get("/payment-options")
def payment_options(user: CurrentUser) -> dict:
    """Moyens de paiement disponibles pour régler l'abonnement depuis ce pays.

    L'agrégateur conseillé est le moins cher acceptant le mobile money : sur nos
    marchés, un parcours de paiement qui exige une carte bancaire écarte la majorité
    des clients dès le premier écran.
    """
    code = (user.get("country") or "BJ").upper()
    recommended = payments.recommended_provider(code)
    return {
        "country": code,
        "currency": countries.get(code).currency,
        "mobile_money": [
            {"key": op.key, "name": op.name, "ussd": op.ussd, "color": op.color}
            for op in payments.operators_for(code)
        ],
        "methods": countries.payment_methods(code),
        "recommended_provider": (
            {
                "key": recommended.key, "name": recommended.name,
                "fee_percent": recommended.fee_percent,
                "settlement_days": recommended.settlement_days,
            }
            if recommended
            else None
        ),
    }
