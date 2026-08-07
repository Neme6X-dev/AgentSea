"""Catalogue d'offres et quotas associés.

⚠️ **La grille tarifaire est un point de départ, pas une décision.** Elle est ici pour
que la plateforme sache compter, facturer et bloquer dès aujourd'hui ; les montants se
changent dans ce seul fichier quand la stratégie commerciale sera arrêtée.

Trois partis pris qui, eux, tiennent quel que soit le prix retenu :

1. **Les prix sont libellés en FCFA, pas convertis depuis l'euro.** Afficher
   « 5,99 € (≈ 3 930 FCFA) » signale à un client de Cotonou qu'il paie le tarif
   d'un autre marché. Le prix de référence est local ; c'est l'international qui est
   converti.
2. **Le tarif est indexé sur le pouvoir d'achat du pays**, via `PRICE_TIERS`. Le même
   plan ne coûte pas la même chose à Niamey et à Johannesburg — et facturer partout
   le prix sud-africain revient à fermer les marchés qui sont notre cœur de cible.
3. **Le palier gratuit publie de vrais sites.** Un essai qui ne met rien en ligne ne
   démontre rien. La limite porte sur le volume et la marque, pas sur la mise en
   ligne elle-même.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.africa import countries, currencies

#: Devise dans laquelle toute la grille est définie. Les autres en découlent.
BASE_CURRENCY = "XOF"


@dataclass(frozen=True)
class Quotas:
    """Limites d'un plan.

    `-1` vaut « sans limite ». On évite `None`, qui obligerait chaque contrôle à
    distinguer trois cas (absent / illimité / valeur) là où deux suffisent.
    """

    sites: int = 1
    generations_per_month: int = 5
    versions_per_site: int = 3
    team_seats: int = 1
    storage_mb: int = 50
    custom_domain: bool = False
    remove_branding: bool = False
    api_access: bool = False
    priority_queue: bool = False
    analytics: bool = False
    seo_tools: bool = False
    export_code: bool = False
    white_label: bool = False
    support: str = "communaute"  # communaute | email | whatsapp | dedie


@dataclass(frozen=True)
class Plan:
    """Une offre commerciale.

    Attributes:
        monthly_xof: prix mensuel de référence en FCFA, pour un pays de palier 1.
        yearly_xof: prix annuel de référence. Fixé à dix mois : deux mois offerts,
            argument d'engagement lisible sans calcul.
    """

    key: str
    name: str
    tagline: str
    monthly_xof: int
    yearly_xof: int
    quotas: Quotas
    audience: str = ""
    highlights: tuple[str, ...] = ()
    popular: bool = False


PLANS: dict[str, Plan] = {
    "decouverte": Plan(
        key="decouverte",
        name="Découverte",
        tagline="Publiez votre premier site, gratuitement.",
        monthly_xof=0,
        yearly_xof=0,
        audience="Particuliers, artisans, test avant achat",
        quotas=Quotas(
            sites=1, generations_per_month=5, versions_per_site=3, storage_mb=50,
            support="communaute",
        ),
        highlights=(
            "1 site en ligne sur un sous-domaine jarvis.africa",
            "5 générations par mois",
            "Hébergement et certificat HTTPS inclus",
            "Mention « Créé avec Jarvis » en pied de page",
        ),
    ),
    "essentiel": Plan(
        key="essentiel",
        name="Essentiel",
        tagline="Votre nom de domaine, votre image.",
        monthly_xof=3_500,
        yearly_xof=35_000,
        audience="Artisans, commerçants, indépendants",
        quotas=Quotas(
            sites=1, generations_per_month=40, versions_per_site=10, storage_mb=500,
            custom_domain=True, remove_branding=True, seo_tools=True, support="whatsapp",
        ),
        highlights=(
            "Nom de domaine personnalisé",
            "40 générations par mois",
            "Sans mention Jarvis",
            "Optimisation SEO locale (Google Business, mots-clés du pays)",
            "Support WhatsApp",
        ),
    ),
    "pro": Plan(
        key="pro",
        name="Pro",
        tagline="Plusieurs sites, vos statistiques, vos exports.",
        monthly_xof=9_500,
        yearly_xof=95_000,
        audience="PME, professions libérales, agences débutantes",
        popular=True,
        quotas=Quotas(
            sites=3, generations_per_month=150, versions_per_site=25, team_seats=3,
            storage_mb=2_000, custom_domain=True, remove_branding=True, analytics=True,
            seo_tools=True, export_code=True, priority_queue=True, support="whatsapp",
        ),
        highlights=(
            "3 sites, 3 collaborateurs",
            "150 générations par mois",
            "Statistiques de fréquentation",
            "Export du code source",
            "File de génération prioritaire",
        ),
    ),
    "business": Plan(
        key="business",
        name="Business",
        tagline="Pour les équipes qui gèrent plusieurs marques.",
        monthly_xof=25_000,
        yearly_xof=250_000,
        audience="Groupes, franchises, ONG, institutions",
        quotas=Quotas(
            sites=10, generations_per_month=500, versions_per_site=50, team_seats=10,
            storage_mb=10_000, custom_domain=True, remove_branding=True, analytics=True,
            seo_tools=True, export_code=True, api_access=True, priority_queue=True,
            support="dedie",
        ),
        highlights=(
            "10 sites, 10 collaborateurs",
            "500 générations par mois",
            "Accès API",
            "Interlocuteur dédié",
        ),
    ),
    "agence": Plan(
        key="agence",
        name="Agence",
        tagline="Revendez sous votre propre marque.",
        monthly_xof=75_000,
        yearly_xof=750_000,
        audience="Agences web, intégrateurs, revendeurs",
        quotas=Quotas(
            sites=50, generations_per_month=-1, versions_per_site=-1, team_seats=25,
            storage_mb=50_000, custom_domain=True, remove_branding=True, analytics=True,
            seo_tools=True, export_code=True, api_access=True, priority_queue=True,
            white_label=True, support="dedie",
        ),
        highlights=(
            "50 sites, générations sans limite",
            "Marque blanche complète",
            "API et webhooks",
            "Tarif revendeur sur les domaines",
        ),
    ),
}

DEFAULT_PLAN = "decouverte"

#: Coefficient appliqué au tarif de référence, par pays.
#:
#: Indexé sur le pouvoir d'achat local, pas sur le taux de change : un site vitrine
#: n'a pas la même valeur perçue à Niamey et au Cap. Le palier 1 correspond au marché
#: de référence (UEMOA hors Côte d'Ivoire et Sénégal).
PRICE_TIERS: dict[str, Decimal] = {
    # Palier 1 — référence
    "BJ": Decimal("1.0"), "BF": Decimal("1.0"), "ML": Decimal("1.0"), "NE": Decimal("1.0"),
    "TD": Decimal("1.0"), "CF": Decimal("1.0"), "GW": Decimal("1.0"), "GN": Decimal("1.0"),
    "CD": Decimal("1.0"), "MG": Decimal("1.0"), "ET": Decimal("1.0"), "TG": Decimal("1.0"),
    # Palier 2 — économies urbaines plus larges
    "CI": Decimal("1.2"), "SN": Decimal("1.2"), "CM": Decimal("1.2"), "CG": Decimal("1.2"),
    "GA": Decimal("1.3"), "UG": Decimal("1.1"), "TZ": Decimal("1.1"), "RW": Decimal("1.1"),
    "NG": Decimal("1.1"), "GH": Decimal("1.2"), "KE": Decimal("1.3"), "EG": Decimal("1.2"),
    "DZ": Decimal("1.3"), "TN": Decimal("1.4"),
    # Palier 3 — marchés à haut pouvoir d'achat
    "MA": Decimal("1.5"), "ZA": Decimal("1.8"), "MU": Decimal("1.8"), "GQ": Decimal("1.5"),
}
DEFAULT_TIER = Decimal("1.5")  # hors Afrique : diaspora, tarif international


def get(key: str | None) -> Plan:
    """Plan par clé, repli sur l'offre gratuite.

    Le repli est volontairement le plan le plus restrictif : si l'abonnement d'un
    compte devient illisible, la plateforme doit sous-servir, jamais sur-servir.
    """
    return PLANS.get((key or "").strip().lower(), PLANS[DEFAULT_PLAN])


def tier_for(country_code: str | None) -> Decimal:
    return PRICE_TIERS.get((country_code or "").strip().upper(), DEFAULT_TIER)


def price_for(plan_key: str, country_code: str, *, yearly: bool = False) -> dict:
    """Prix affichable d'un plan dans un pays donné.

    Returns:
        Un dictionnaire prêt pour l'API et le gabarit : montant numérique, devise,
        montant formaté, et — sur l'annuel — l'équivalent mensuel, qui est le chiffre
        que le client compare réellement.
    """
    plan = get(plan_key)
    country = countries.get(country_code)
    base = plan.yearly_xof if yearly else plan.monthly_xof

    if base == 0:
        return {
            "plan": plan.key, "amount": 0, "currency": country.currency,
            "formatted": "Gratuit", "period": "an" if yearly else "mois",
            "monthly_equivalent": 0, "monthly_equivalent_formatted": "Gratuit",
        }

    amount_xof = Decimal(base) * tier_for(country.code)
    amount = currencies.convert(amount_xof, BASE_CURRENCY, country.currency)
    amount = currencies.round_to_step(amount, country.currency)

    monthly = currencies.round_to_step(Decimal(amount) / 12, country.currency) if yearly else amount
    # Le français suffit à emporter le format même s'il n'est pas la langue première :
    # au Maroc et en Tunisie, les prix s'écrivent « 234,00 DH » et non « 234.00 ».
    locale = "fr" if "fr" in country.languages else "en"

    return {
        "plan": plan.key,
        "amount": amount,
        "currency": country.currency,
        "formatted": currencies.format_amount(amount, country.currency, locale=locale),
        "period": "an" if yearly else "mois",
        "monthly_equivalent": monthly,
        "monthly_equivalent_formatted": currencies.format_amount(monthly, country.currency, locale=locale),
    }


def catalog(country_code: str) -> list[dict]:
    """Grille complète pour un pays, telle que la page tarifs doit l'afficher."""
    return [
        {
            "key": plan.key,
            "name": plan.name,
            "tagline": plan.tagline,
            "audience": plan.audience,
            "popular": plan.popular,
            "highlights": list(plan.highlights),
            "monthly": price_for(plan.key, country_code),
            "yearly": price_for(plan.key, country_code, yearly=True),
            "quotas": quotas_public(plan.key),
        }
        for plan in PLANS.values()
    ]


def quotas_public(plan_key: str) -> dict:
    """Quotas d'un plan, sérialisables et lisibles par le front."""
    q = get(plan_key).quotas
    return {
        "sites": q.sites,
        "generations_per_month": q.generations_per_month,
        "versions_per_site": q.versions_per_site,
        "team_seats": q.team_seats,
        "storage_mb": q.storage_mb,
        "custom_domain": q.custom_domain,
        "remove_branding": q.remove_branding,
        "api_access": q.api_access,
        "priority_queue": q.priority_queue,
        "analytics": q.analytics,
        "seo_tools": q.seo_tools,
        "export_code": q.export_code,
        "white_label": q.white_label,
        "support": q.support,
    }


def monthly_revenue_xof(plan_key: str, country_code: str, *, yearly: bool = False) -> int:
    """Revenu mensuel normalisé en FCFA, pour consolider le MRR du dashboard.

    Un abonnement annuel est ramené au douzième : mélanger des paiements annuels et
    mensuels dans un même total ferait bondir la courbe au moment de l'encaissement
    puis chuter les onze mois suivants, sans qu'aucune activité réelle n'ait changé.
    """
    plan = get(plan_key)
    base = Decimal(plan.yearly_xof) / 12 if yearly else Decimal(plan.monthly_xof)
    return int(base * tier_for(country_code))
