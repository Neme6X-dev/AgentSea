"""Endpoints publics, sans authentification.

Deux usages seulement, et rien d'autre ne doit venir s'y ajouter sans raison forte :

1. **Référentiels** (pays, devises, offres) — consommés par la page d'inscription et
   la page de tarification, qui s'affichent avant toute connexion. Les servir depuis
   l'API plutôt que de les figer dans le bundle du front garantit qu'ouvrir un pays
   ne demande pas de redéployer l'interface.
2. **Balise de fréquentation** — appelée par les sites publiés eux-mêmes.

Ces routes sont couvertes par `PublicRateLimitMiddleware` : ce sont les seules
joignables sans jeton, donc les seules qu'un script peut marteler gratuitement.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status

from app import db
from app.africa import countries, currencies, locales
from app.analytics import events
from app.billing import plans
from app.config import settings
from app.contracts import PlanOffer, VisitBeacon

logger = logging.getLogger("app.public")

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/countries")
def list_countries() -> list[dict]:
    """Pays ouverts à l'inscription, avec ce qu'il faut pour préremplir le formulaire.

    L'ordre est celui du registre — marché principal en tête — et non l'ordre
    alphabétique : un commerçant béninois ne doit pas faire défiler l'Afrique du Sud,
    l'Algérie et l'Égypte avant de trouver son pays.
    """
    allowed = set(settings.enabled_countries)
    return [
        {
            "code": c.code,
            "name": c.name_fr,
            "name_en": c.name_en,
            "flag": c.flag,
            "dial_code": c.dial_code,
            "currency": c.currency,
            "currency_symbol": currencies.get(c.currency).symbol,
            "languages": list(c.languages),
            "cities": list(c.major_cities),
            "mobile_money": list(c.mobile_money),
            "phone_example": _phone_example(c),
        }
        for c in countries.list_countries()
        if not allowed or c.code in allowed
    ]


def _phone_example(country: countries.Country) -> str:
    """Exemple de numéro au bon format, pour le `placeholder` du champ téléphone.

    Un exemple concret vaut mieux qu'une consigne : « 01 97 00 00 00 » se recopie,
    « saisissez un numéro à 10 chiffres » se lit puis s'oublie.
    """
    from app.africa import phone as phonelib

    length = country.national_digits[0]
    prefix = country.mobile_prefixes[0] if country.mobile_prefixes else "0"
    body = (prefix + "0" * length)[:length]
    return phonelib.format_national(body, country.code)


@router.get("/countries/{code}")
def country_profile(code: str) -> dict:
    """Profil complet d'un pays : paiement, horaires, adressage, conventions."""
    country = countries.get(code)
    profile = locales.profile(country.code)
    return {
        "code": country.code,
        "name": country.name_fr,
        "flag": country.flag,
        "dial_code": country.dial_code,
        "currency": country.currency,
        "currency_symbol": currencies.get(country.currency).symbol,
        "timezone": country.timezone,
        "languages": list(country.languages),
        "economic_zone": country.economic_zone,
        "vat_rate": country.vat_rate,
        "cities": list(country.major_cities),
        "payment_methods": countries.payment_methods(country.code),
        "business_hours_hint": locales.business_hours_hint(country.code),
        "address_hint": locales.address_hint(country.code),
        "date_format": profile.date_format,
        "rtl": profile.rtl,
    }


@router.get("/plans", response_model=list[PlanOffer])
def public_plans(country: str = "BJ") -> list[PlanOffer]:
    """Grille tarifaire publique, dans la devise du pays demandé."""
    return [PlanOffer(**offer) for offer in plans.catalog(country.upper())]


@router.post("/beacon", status_code=status.HTTP_204_NO_CONTENT)
def visit_beacon(payload: VisitBeacon, request: Request) -> Response:
    """Enregistre une vue ou un clic de contact sur un site publié.

    Répond systématiquement 204, y compris pour un slug inconnu. Deux raisons : le
    script appelant utilise `navigator.sendBeacon`, qui ignore la réponse de toute
    façon ; et distinguer un slug connu d'un slug inconnu offrirait à n'importe qui un
    moyen d'énumérer les sites hébergés.

    L'événement `whatsapp` ou `call` est celui qui compte réellement : c'est la
    conversion d'un site vitrine africain, bien avant le temps passé sur la page.
    """
    session = db.get_session_by_slug(payload.slug)
    if session is not None:
        country = _visitor_country(request) or session.get("country")
        events.record_visit(
            session["id"],
            country=country,
            views=1 if payload.event == "view" else 0,
            visitors=1 if (payload.event == "view" and payload.unique) else 0,
            whatsapp_clicks=1 if payload.event == "whatsapp" else 0,
            call_clicks=1 if payload.event == "call" else 0,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _visitor_country(request: Request) -> str | None:
    """Pays du visiteur, tel que le déclare le proxy en amont.

    Cloudflare renseigne `CF-IPCountry` ; d'autres en-têtes équivalents existent. On
    ne fait **aucune** géolocalisation par IP nous-mêmes : cela supposerait d'embarquer
    une base à tenir à jour, pour une précision dont la ventilation par pays n'a pas
    besoin. Sans en-tête, on retombe sur le pays du site — approximation honnête,
    puisqu'un site vitrine local est très majoritairement consulté depuis son pays.
    """
    for header in ("CF-IPCountry", "X-Country-Code", "X-Vercel-IP-Country"):
        value = request.headers.get(header, "").strip().upper()
        if len(value) == 2 and value.isalpha() and value != "XX":
            return value
    return None
