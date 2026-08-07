"""Encaissement en Afrique : opérateurs mobile money et agrégateurs de paiement.

Deux registres distincts, souvent confondus :

- **Les opérateurs mobile money** (MTN MoMo, Orange Money, Wave, M-Pesa…) sont ce que
  le *client final* utilise. Ils apparaissent sur les sites générés : « Paiement
  accepté : MTN MoMo, Moov Money ».
- **Les agrégateurs (PSP)** sont ce que *la plateforme* branche pour encaisser ses
  propres abonnements. Un seul PSP donne accès à plusieurs opérateurs à la fois.

Le module ne réalise aucune transaction : il décrit le paysage pour que le choix
d'intégration soit une décision documentée plutôt qu'un `if` perdu dans un routeur.
Les frais indiqués servent au calcul de la marge nette dans le dashboard admin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.africa import countries


@dataclass(frozen=True)
class MobileMoneyOperator:
    """Un opérateur de paiement mobile, du point de vue du client final."""

    key: str
    name: str
    countries: tuple[str, ...]
    ussd: str = ""      # code de composition, souvent la seule chose que le client connaît
    color: str = "#666" # couleur de marque, pour les badges de paiement d'un site généré


MOBILE_MONEY: dict[str, MobileMoneyOperator] = {
    "mtn-momo": MobileMoneyOperator(
        "mtn-momo", "MTN MoMo",
        ("BJ", "CM", "CI", "GH", "GN", "RW", "UG", "CG", "GW", "ZA"),
        "*880#", "#FFCC00",
    ),
    "orange-money": MobileMoneyOperator(
        "orange-money", "Orange Money",
        ("CI", "SN", "ML", "BF", "GN", "CM", "CF", "CD", "MG"),
        "#144#", "#FF7900",
    ),
    "moov-money": MobileMoneyOperator(
        "moov-money", "Moov Money",
        ("BJ", "CI", "TG", "BF", "ML", "NE", "GA", "TD"),
        "*855#", "#0066B3",
    ),
    "wave": MobileMoneyOperator(
        "wave", "Wave", ("SN", "CI", "ML", "BF", "GM", "UG"), "", "#1DC8FF",
    ),
    "m-pesa": MobileMoneyOperator(
        "m-pesa", "M-Pesa", ("KE", "TZ", "CD", "MZ", "LS", "GH", "EG"), "*334#", "#00A651",
    ),
    "airtel-money": MobileMoneyOperator(
        "airtel-money", "Airtel Money",
        ("NE", "TD", "GA", "CG", "CD", "KE", "UG", "TZ", "RW", "MG"),
        "*150#", "#ED1C24",
    ),
    "free-money": MobileMoneyOperator("free-money", "Free Money", ("SN",), "#150#", "#CD1C2E"),
    "t-money": MobileMoneyOperator("t-money", "T-Money", ("TG",), "*145#", "#005BAA"),
    "celtiis-cash": MobileMoneyOperator("celtiis-cash", "Celtiis Cash", ("BJ",), "*880#", "#00843D"),
    "telecel-cash": MobileMoneyOperator("telecel-cash", "Telecel Cash", ("GH", "CF"), "*110#", "#E4002B"),
    "opay": MobileMoneyOperator("opay", "OPay", ("NG",), "", "#1A7F64"),
    "palmpay": MobileMoneyOperator("palmpay", "PalmPay", ("NG",), "", "#8B2FC9"),
    "moniepoint": MobileMoneyOperator("moniepoint", "Moniepoint", ("NG",), "", "#0357EE"),
    "mvola": MobileMoneyOperator("mvola", "MVola", ("MG",), "#111#", "#FDB913"),
    "telebirr": MobileMoneyOperator("telebirr", "Telebirr", ("ET",), "*127#", "#00A94F"),
    "vodafone-cash": MobileMoneyOperator("vodafone-cash", "Vodafone Cash", ("EG",), "*9#", "#E60000"),
}


@dataclass(frozen=True)
class PaymentProvider:
    """Un agrégateur susceptible d'encaisser les abonnements de la plateforme.

    Attributes:
        fee_percent / fee_fixed: frais annoncés, servant à estimer la marge nette.
            `fee_fixed` est exprimé dans la devise dominante du PSP.
        settlement_days: délai de reversement, dimension déterminante pour la
            trésorerie quand on encaisse en FCFA et qu'on paie des API en dollars.
        payout_currencies: devises dans lesquelles le PSP reverse réellement.
    """

    key: str
    name: str
    countries: tuple[str, ...]
    methods: tuple[str, ...]
    fee_percent: float
    fee_fixed: int = 0
    fee_currency: str = "XOF"
    settlement_days: int = 2
    payout_currencies: tuple[str, ...] = ()
    docs: str = ""
    notes: str = ""


PROVIDERS: dict[str, PaymentProvider] = {
    "kkiapay": PaymentProvider(
        "kkiapay", "KKiaPay", ("BJ", "CI", "TG", "SN", "BF", "ML"),
        ("mobile-money", "carte"), 1.8, 0, "XOF", 1, ("XOF",),
        "https://docs.kkiapay.me",
        "Intégration la plus directe sur le marché béninois : widget JS, reversement J+1.",
    ),
    "fedapay": PaymentProvider(
        "fedapay", "FedaPay", ("BJ", "CI", "TG", "SN", "NE", "GN"),
        ("mobile-money", "carte"), 2.0, 0, "XOF", 2, ("XOF",),
        "https://docs.fedapay.com",
        "Bonne couverture UEMOA, API REST simple, sandbox complète.",
    ),
    "cinetpay": PaymentProvider(
        "cinetpay", "CinetPay",
        ("CI", "SN", "BF", "ML", "TG", "BJ", "CM", "GN", "NE", "CD", "GA"),
        ("mobile-money", "carte", "wallet"), 3.0, 0, "XOF", 3, ("XOF", "XAF"),
        "https://docs.cinetpay.com",
        "La plus large couverture francophone en un seul contrat. Frais plus élevés.",
    ),
    "paydunya": PaymentProvider(
        "paydunya", "PayDunya", ("SN", "CI", "BJ", "BF", "TG", "ML"),
        ("mobile-money", "carte"), 2.5, 0, "XOF", 2, ("XOF",),
        "https://paydunya.com/developers", "Forte présence Sénégal, intègre Wave nativement.",
    ),
    "wave": PaymentProvider(
        "wave", "Wave", ("SN", "CI", "ML", "BF"), ("mobile-money",), 1.0, 0, "XOF", 1, ("XOF",),
        "https://docs.wave.com",
        "Frais les plus bas de la zone. Un seul moyen de paiement : à combiner.",
    ),
    "paystack": PaymentProvider(
        "paystack", "Paystack", ("NG", "GH", "ZA", "KE", "CI"),
        ("carte", "mobile-money", "virement"), 1.5, 100, "NGN", 1, ("NGN", "GHS", "ZAR", "KES"),
        "https://paystack.com/docs",
        "Référence anglophone. Frais fixes annulés sous 2 500 NGN.",
    ),
    "flutterwave": PaymentProvider(
        "flutterwave", "Flutterwave",
        ("NG", "GH", "KE", "UG", "TZ", "RW", "ZA", "CM", "CI", "SN", "EG"),
        ("carte", "mobile-money", "virement"), 3.8, 0, "USD", 3,
        ("NGN", "GHS", "KES", "UGX", "TZS", "RWF", "ZAR", "XAF", "XOF", "USD"),
        "https://developer.flutterwave.com",
        "Couverture panafricaine en un contrat. Frais élevés à l'international.",
    ),
    "paymob": PaymentProvider(
        "paymob", "Paymob", ("EG", "MA"), ("carte", "wallet"), 2.75, 0, "EGP", 3, ("EGP", "MAD"),
        "https://docs.paymob.com", "Référence Égypte, en expansion au Maroc.",
    ),
    "stripe": PaymentProvider(
        "stripe", "Stripe", ("ZA", "NG", "MU"), ("carte",), 2.9, 30, "USD", 7, ("USD", "EUR", "ZAR"),
        "https://stripe.com/docs",
        "Pour la diaspora et les clients hors zone. Non disponible en UEMOA.",
    ),
}


def operators_for(country_code: str) -> list[MobileMoneyOperator]:
    """Opérateurs mobile money d'un pays, dans l'ordre de part de marché.

    L'ordre vient du registre pays (`Country.mobile_money`), qui reflète l'usage réel,
    et non de l'ordre de déclaration de ce module.
    """
    country = countries.get(country_code)
    by_name = {op.name.lower(): op for op in MOBILE_MONEY.values()}
    out: list[MobileMoneyOperator] = []
    for label in country.mobile_money:
        op = by_name.get(label.lower())
        if op is None:
            # Certaines entrées du registre pays sont des moyens de paiement sans
            # opérateur dédié (« Virement bancaire », « Carte bancaire ») : on les
            # laisse au registre pays, qui les expose via `payment_methods()`.
            continue
        out.append(op)
    return out


def providers_for(country_code: str) -> list[PaymentProvider]:
    """PSP couvrant un pays, du moins cher au plus cher.

    Le tri par coût est intentionnel : sur des abonnements à quelques milliers de
    FCFA, un point de commission fait plusieurs pourcents de la marge.
    """
    code = (country_code or "").strip().upper()
    matching = [p for p in PROVIDERS.values() if code in p.countries]
    return sorted(matching, key=lambda p: p.fee_percent)


def recommended_provider(country_code: str) -> PaymentProvider | None:
    """PSP conseillé pour encaisser dans ce pays.

    Le moins cher qui accepte le mobile money : sur nos marchés, un PSP « carte
    seulement » écarte la majorité des payeurs, quel que soit son tarif.
    """
    for provider in providers_for(country_code):
        if "mobile-money" in provider.methods:
            return provider
    candidates = providers_for(country_code)
    return candidates[0] if candidates else None


def estimate_fees(amount: float, provider_key: str) -> float:
    """Frais d'encaissement estimés pour un montant, dans la devise du montant.

    Approximation assumée : la part fixe est comptée telle quelle, sans conversion
    depuis `fee_currency`. Elle est marginale devant la part proportionnelle sur les
    montants concernés, et le dashboard affiche une tendance, pas une comptabilité.
    """
    provider = PROVIDERS.get(provider_key)
    if provider is None:
        return 0.0
    return round(amount * provider.fee_percent / 100 + provider.fee_fixed, 2)


def payment_badges(country_code: str) -> list[dict[str, str]]:
    """Moyens de paiement à afficher sur un site généré, prêts pour le gabarit.

    Retourne des dictionnaires plats (`name`, `color`, `ussd`) parce que ce bloc part
    dans le contexte de l'agent codeur : un modèle rend un JSON plat bien plus
    fidèlement qu'une structure imbriquée.
    """
    badges = [
        {"name": op.name, "color": op.color, "ussd": op.ussd}
        for op in operators_for(country_code)
    ]
    known = {b["name"] for b in badges}
    for extra in countries.payment_methods(country_code):
        if extra not in known:
            badges.append({"name": extra, "color": "#4B5563", "ussd": ""})
    return badges
