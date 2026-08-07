"""Devises africaines : définition, formatage et conversion de référence.

Ce module existe parce que formater un montant « comme en Europe » produit des prix
faux sur nos marchés. Trois pièges concrets, tous rencontrés en production ailleurs :

1. **Le franc CFA n'a pas de décimales.** « 15 000,00 FCFA » n'existe pas ; on écrit
   « 15 000 FCFA ». Un `:.2f` générique ajoute deux zéros qui font amateur.
2. **Le symbole se place à droite** dans la zone franc, à gauche au Nigeria (₦5,000)
   et en Afrique du Sud (R 250). Le placement fait partie de la devise, pas du thème.
3. **Le séparateur de milliers est l'espace insécable** en français, la virgule en
   anglais. Copier le format anglais dans une page francophone donne « 15,000 FCFA »,
   qu'un client béninois lit comme quinze virgule zéro.

Les taux servent uniquement à afficher un ordre de grandeur (grille tarifaire,
agrégats du dashboard admin) — jamais à encaisser. Le XOF et le XAF ont une parité
fixe avec l'euro, les autres flottent : voir `RATES_TO_XOF`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# Parité fixe garantie par le Trésor français : 1 EUR = 655,957 XOF (et XAF).
# C'est une constante juridique, pas un taux de marché : elle ne bouge pas.
EUR_TO_XOF = Decimal("655.957")


@dataclass(frozen=True)
class Currency:
    """Une devise et tout ce qu'il faut pour l'afficher correctement.

    Attributes:
        code: code ISO 4217 (XOF, NGN…).
        symbol: symbole d'affichage courant. « FCFA » est un sigle, pas un symbole
            Unicode : c'est pourtant ce que les commerçants écrivent sur leurs pages.
        name_fr / name_en: libellé long, pour les listes déroulantes.
        decimals: nombre de décimales *effectivement utilisées dans le commerce*.
            Le TZS a bien 2 décimales sur le papier, mais aucun prix affiché ne les
            emploie — on met 0 pour coller à l'usage réel.
        symbol_first: symbole avant le montant (₦5 000) ou après (5 000 FCFA).
        symbol_space: espace entre symbole et montant. Un symbole graphique se colle
            (`₦5 000`, `$12`), un sigle alphabétique se sépare (`KSh 500`, `R 250`) —
            sans quoi `R250` se lit comme un code produit.
        step: incrément de prix naturel. En zone CFA, personne n'affiche 12 347 FCFA :
            on arrondit au multiple de 5 (pièces) ou de 500 pour un tarif d'abonnement.
    """

    code: str
    symbol: str
    name_fr: str
    name_en: str
    decimals: int = 2
    symbol_first: bool = False
    step: int = 1
    symbol_space: bool = True


CURRENCIES: dict[str, Currency] = {
    # --- Zone franc : cœur de cible ------------------------------------------ #
    "XOF": Currency("XOF", "FCFA", "Franc CFA (UEMOA)", "West African CFA franc", 0, False, 5),
    "XAF": Currency("XAF", "FCFA", "Franc CFA (CEMAC)", "Central African CFA franc", 0, False, 5),
    # --- Grandes économies anglophones --------------------------------------- #
    "NGN": Currency("NGN", "₦", "Naira nigérian", "Nigerian naira", 2, True, 50, symbol_space=False),
    "GHS": Currency("GHS", "GH₵", "Cedi ghanéen", "Ghanaian cedi", 2, True, 1, symbol_space=False),
    "KES": Currency("KES", "KSh", "Shilling kényan", "Kenyan shilling", 2, True, 5),
    "ZAR": Currency("ZAR", "R", "Rand sud-africain", "South African rand", 2, True, 1),
    "UGX": Currency("UGX", "USh", "Shilling ougandais", "Ugandan shilling", 0, True, 100),
    "TZS": Currency("TZS", "TSh", "Shilling tanzanien", "Tanzanian shilling", 0, True, 100),
    "RWF": Currency("RWF", "FRw", "Franc rwandais", "Rwandan franc", 0, False, 100),
    "ETB": Currency("ETB", "Br", "Birr éthiopien", "Ethiopian birr", 2, True, 1),
    "MUR": Currency("MUR", "Rs", "Roupie mauricienne", "Mauritian rupee", 2, True, 1),
    # --- Maghreb -------------------------------------------------------------- #
    "MAD": Currency("MAD", "DH", "Dirham marocain", "Moroccan dirham", 2, False, 1),
    "TND": Currency("TND", "DT", "Dinar tunisien", "Tunisian dinar", 3, False, 1),
    "DZD": Currency("DZD", "DA", "Dinar algérien", "Algerian dinar", 2, False, 10),
    "EGP": Currency("EGP", "E£", "Livre égyptienne", "Egyptian pound", 2, True, 5, symbol_space=False),
    # --- Autres --------------------------------------------------------------- #
    "CDF": Currency("CDF", "FC", "Franc congolais", "Congolese franc", 0, False, 100),
    "GNF": Currency("GNF", "FG", "Franc guinéen", "Guinean franc", 0, False, 1000),
    "MGA": Currency("MGA", "Ar", "Ariary malgache", "Malagasy ariary", 0, False, 100),
    # --- Internationales, pour la diaspora et les tarifs de référence --------- #
    "USD": Currency("USD", "$", "Dollar américain", "US dollar", 2, True, 1, symbol_space=False),
    "EUR": Currency("EUR", "€", "Euro", "Euro", 2, False, 1),
}

DEFAULT_CURRENCY = "XOF"

# Taux indicatifs vers le XOF, servant aux agrégats multi-pays du dashboard admin.
# Ils sont volontairement approximatifs et figés dans le code : un dashboard interne
# n'a pas besoin d'un taux au centime, et dépendre d'une API de change pour afficher
# un chiffre d'affaires consolidé ferait tomber la page dès que l'API tombe.
# `refresh_rates()` permet de les recharger depuis une source réelle si le besoin
# apparaît, sans changer les appelants.
RATES_TO_XOF: dict[str, Decimal] = {
    "XOF": Decimal("1"),
    "XAF": Decimal("1"),  # même parité, deux banques centrales
    "EUR": EUR_TO_XOF,
    "USD": Decimal("605"),
    "NGN": Decimal("0.40"),
    "GHS": Decimal("50"),
    "KES": Decimal("4.7"),
    "ZAR": Decimal("33"),
    "UGX": Decimal("0.16"),
    "TZS": Decimal("0.23"),
    "RWF": Decimal("0.44"),
    "ETB": Decimal("4.8"),
    "MUR": Decimal("13"),
    "MAD": Decimal("61"),
    "TND": Decimal("195"),
    "DZD": Decimal("4.5"),
    "EGP": Decimal("12.5"),
    "CDF": Decimal("0.21"),
    "GNF": Decimal("0.070"),
    "MGA": Decimal("0.13"),
}


def get(code: str) -> Currency:
    """Devise par son code ISO, repli sur le franc CFA ouest-africain.

    Le repli n'est pas une facilité : un code inconnu vient forcément d'une saisie
    utilisateur ou d'un spec produit par un modèle. Lever ici ferait échouer une
    génération de site pour une faute de frappe dans un champ décoratif.
    """
    return CURRENCIES.get((code or "").strip().upper(), CURRENCIES[DEFAULT_CURRENCY])


def format_amount(amount: float | int | Decimal, code: str = DEFAULT_CURRENCY, *, locale: str = "fr") -> str:
    """Formate un montant selon les usages du pays de la devise.

    Args:
        amount: montant dans l'unité principale (pas en centimes).
        code: code ISO de la devise.
        locale: `fr` (espace insécable en séparateur, virgule décimale) ou `en`
            (virgule en séparateur, point décimal).

    Returns:
        Le montant prêt à afficher, symbole compris.

    Examples:
        >>> format_amount(15000, "XOF")
        '15 000 FCFA'
        >>> format_amount(5000, "NGN", locale="en")
        '₦5,000.00'
    """
    cur = get(code)
    quantum = Decimal(1).scaleb(-cur.decimals)
    value = Decimal(str(amount)).quantize(quantum, rounding=ROUND_HALF_UP)

    entier, _, frac = f"{abs(value):f}".partition(".")
    groups = _group_thousands(entier)

    if locale.startswith("fr"):
        # U+202F, espace fine insécable : c'est la règle typographique française et
        # elle empêche « 15 » et « 000 » de se retrouver sur deux lignes différentes.
        body = " ".join(groups)
        if cur.decimals:
            body = f"{body},{frac}"
    else:
        body = ",".join(groups)
        if cur.decimals:
            body = f"{body}.{frac}"

    if value < 0:
        body = f"-{body}"
    # Espace insécable entre montant et symbole : « 15 000 FCFA » ne doit jamais se
    # couper en fin de ligne.
    gap = " " if cur.symbol_space else ""
    return f"{cur.symbol}{gap}{body}" if cur.symbol_first else f"{body} {cur.symbol}"


def _group_thousands(digits: str) -> list[str]:
    """Découpe une suite de chiffres en groupes de trois, en partant de la droite."""
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return out


def round_to_step(amount: float | int | Decimal, code: str = DEFAULT_CURRENCY) -> int:
    """Arrondit un montant à l'incrément commercial naturel de la devise.

    Sert aux prix calculés — conversion d'une grille de référence vers la devise
    locale, remise en pourcentage. « 12 347 FCFA » n'est pas un prix qu'on affiche ;
    « 12 345 » non plus. On veut « 12 350 ».
    """
    cur = get(code)
    step = Decimal(cur.step)
    value = Decimal(str(amount))
    return int((value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step)


def convert(amount: float | int | Decimal, source: str, target: str) -> Decimal:
    """Convertit entre deux devises via le XOF comme pivot.

    Le pivot est le XOF et non l'euro ou le dollar : c'est la devise de référence de
    la plateforme, celle dans laquelle les agrégats du dashboard sont consolidés.
    Un aller-retour de moins veut dire une erreur d'arrondi de moins sur le chiffre
    que le dirigeant lit tous les matins.
    """
    src = RATES_TO_XOF.get(source.upper())
    dst = RATES_TO_XOF.get(target.upper())
    if src is None or dst is None:
        raise ValueError(f"Taux indisponible pour {source}→{target}")
    return Decimal(str(amount)) * src / dst


def to_xof(amount: float | int | Decimal, code: str) -> Decimal:
    """Montant converti en XOF, la devise de consolidation des rapports internes."""
    return convert(amount, code, "XOF")


def refresh_rates(rates: dict[str, float | Decimal]) -> None:
    """Remplace les taux indicatifs (une tâche planifiée peut les rafraîchir).

    Le XOF et le XAF sont ignorés : leur parité est fixée par traité, une source de
    marché ne peut que la dégrader.
    """
    for code, rate in rates.items():
        code = code.upper()
        if code in {"XOF", "XAF"} or code not in CURRENCIES:
            continue
        RATES_TO_XOF[code] = Decimal(str(rate))
