"""Numéros de téléphone africains : reconnaissance, normalisation, affichage.

Le besoin naît d'un garde-fou existant : la validation rejette tout numéro affiché
sur un site généré mais absent du spec, pour empêcher le modèle d'inventer des
coordonnées. Ce garde-fou ne reconnaissait que le format français (`+33` ou `0` suivi
de neuf chiffres). Conséquence : un numéro béninois `+229 01 97 00 00 00` écrit par le
modèle passait entre les mailles, et un numéro légitimement fourni par le client
n'était pas reconnu comme tel.

Le module couvre trois usages :

- **détecter** les numéros dans un texte libre (contrôle anti-invention) ;
- **normaliser** en E.164 (`+22901970000000`), le seul format qu'acceptent les liens
  `wa.me` et les passerelles SMS ;
- **afficher** dans le groupage attendu localement, qui n'est pas le même partout :
  `01 97 00 00 00` au Bénin, `07 07 07 07 07` en Côte d'Ivoire, `77 123 45 67` au
  Sénégal, `0803 123 4567` au Nigeria.

On n'utilise pas `phonenumbers` (libphonenumber) : la bibliothèque pèse plusieurs
mégaoctets pour une couverture mondiale dont nous exploitons trente pays, et ses
métadonnées suivent mal les migrations de plan de numérotation ouest-africaines.
Le registre de `countries.py` est notre source, et il est corrigible en une ligne.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.africa import countries

# Un numéro plausible dans du texte libre : indicatif optionnel, puis 7 à 14 chiffres
# éventuellement séparés par des espaces, points ou tirets. Volontairement large — le
# tri fin est fait par `parse()`, qui confronte le résultat au registre des pays.
CANDIDATE_RE = re.compile(
    r"(?:(?<![\w.])(?:\+|00)(\d{1,4})[\s.\-]?)?"  # indicatif international
    r"(\d(?:[\s.\-]?\d){6,13})"                    # corps national
    r"(?![\w])"
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")


@dataclass(frozen=True)
class PhoneNumber:
    """Un numéro reconnu et rattaché à un pays."""

    e164: str          # +22901970000000 — format des liens wa.me et des API SMS
    country: str       # code ISO du pays reconnu
    national: str      # chiffres nationaux, sans indicatif ni séparateur
    is_mobile: bool

    def display(self) -> str:
        """Groupage local, tel qu'on l'écrit sur une carte de visite."""
        return format_national(self.national, self.country)

    def international(self) -> str:
        """Format international lisible : `+229 01 97 00 00 00`."""
        return f"+{countries.get(self.country).dial_code} {self.display()}"

    def whatsapp_url(self, message: str = "") -> str:
        """Lien `wa.me` prêt à poser sur un bouton.

        WhatsApp exige l'E.164 **sans** le `+` ni aucun séparateur : toute autre
        forme ouvre l'application sur un écran de recherche vide, ce que
        l'utilisateur interprète comme un bouton cassé.
        """
        from urllib.parse import quote

        base = f"https://wa.me/{self.e164.lstrip('+')}"
        return f"{base}?text={quote(message)}" if message else base

    def tel_url(self) -> str:
        """Lien `tel:` pour le clic-pour-appeler, en E.164 (jamais en format local)."""
        return f"tel:{self.e164}"


def parse(raw: str, default_country: str | None = None) -> PhoneNumber | None:
    """Interprète un numéro et le rattache à un pays. `None` si non reconnu.

    Args:
        raw: numéro tel que saisi (`+229 01 97 00 00 00`, `0197000000`, `97000000`).
        default_country: pays présumé quand le numéro n'a pas d'indicatif. C'est le
            cas le plus fréquent : un commerçant écrit son numéro comme il le
            compose, sans indicatif.

    Returns:
        Le numéro normalisé, ou `None` si aucune longueur connue ne correspond.
    """
    if not raw:
        return None

    text = raw.strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None

    explicit_prefix = text.startswith("+") or text.startswith("00")
    if text.startswith("00"):
        digits = digits[2:]

    # 1. Indicatif explicite : on l'isole en essayant les préfixes du plus long au
    #    plus court, car « 22 » (aucun pays ici) ne doit pas l'emporter sur « 229 ».
    if explicit_prefix:
        for length in (4, 3, 2, 1):
            country = countries.by_dial_code(digits[:length])
            if country and _accepts(country, digits[length:]):
                return _build(country, digits[length:])
        return None

    # 2. Pas d'indicatif explicite, mais le numéro commence par celui d'un pays connu
    #    et la suite a la bonne longueur : cas des numéros copiés sans le `+`.
    for length in (4, 3, 2, 1):
        country = countries.by_dial_code(digits[:length])
        if country and _accepts(country, digits[length:]):
            # Ambiguïté possible avec un numéro national qui commencerait par les
            # mêmes chiffres. Le pays par défaut tranche en sa faveur : c'est lui
            # qui décrit le contexte réel de saisie.
            if default_country:
                presumed = countries.find(default_country)
                if presumed and _accepts(presumed, digits):
                    return _build(presumed, digits)
            return _build(country, digits[length:])

    # 3. Numéro purement national.
    presumed = countries.find(default_country) if default_country else None
    if presumed and _accepts(presumed, digits):
        return _build(presumed, digits)

    return None


def _national_variants(digits: str) -> tuple[str, ...]:
    """Lectures possibles d'un corps national, préfixe interurbain compris.

    Beaucoup de pays écrivent leurs numéros avec un `0` de mise en ligne qui ne fait
    pas partie du numéro international : `0803 123 4567` au Nigeria vaut
    `+234 803 123 4567`. Mais ce n'est pas universel — le `0` initial des numéros
    béninois (`01 97 …`) et congolais fait bien partie du numéro depuis la migration.

    On ne peut donc pas trancher a priori. On propose les deux lectures et c'est la
    longueur déclarée au registre pays qui départage : la lecture littérale d'abord,
    pour que le Bénin garde son zéro.
    """
    if digits.startswith("0") and len(digits) > 1:
        return (digits, digits[1:])
    return (digits,)


def _accepts(country: countries.Country, national: str) -> bool:
    return any(len(v) in country.national_digits for v in _national_variants(national))


def _canonical(country: countries.Country, national: str) -> str:
    """Corps national retenu parmi les lectures acceptables (littérale prioritaire)."""
    for variant in _national_variants(national):
        if len(variant) in country.national_digits:
            return variant
    return national


def _build(country: countries.Country, national: str) -> PhoneNumber:
    body = _canonical(country, national)
    return PhoneNumber(
        e164=f"+{country.dial_code}{body}",
        country=country.code,
        national=body,
        is_mobile=_is_mobile(country, body),
    )


def _is_mobile(country: countries.Country, national: str) -> bool:
    """Vrai si le numéro porte un préfixe mobile connu du pays.

    Faute de préfixes déclarés, on répond `True` : la quasi-totalité des numéros
    professionnels affichés sur nos marchés sont des mobiles, et se tromper dans ce
    sens ne coûte qu'un bouton WhatsApp de trop — l'inverse retire un canal de
    contact que le client attend.
    """
    if not country.mobile_prefixes:
        return True
    return any(national.startswith(p) for p in country.mobile_prefixes)


# Groupage d'affichage par pays. La clé est le nombre de chiffres nationaux, ce qui
# permet de gérer les pays en cours de migration (Bénin : 8 et 10 chiffres coexistent).
_GROUPING: dict[str, dict[int, tuple[int, ...]]] = {
    "BJ": {10: (2, 2, 2, 2, 2), 8: (2, 2, 2, 2)},
    "CI": {10: (2, 2, 2, 2, 2)},
    "SN": {9: (2, 3, 2, 2)},
    "TG": {8: (2, 2, 2, 2)},
    "BF": {8: (2, 2, 2, 2)},
    "ML": {8: (2, 2, 2, 2)},
    "NE": {8: (2, 2, 2, 2)},
    "CM": {9: (1, 2, 2, 2, 2)},
    "GA": {9: (1, 2, 2, 2, 2), 8: (2, 2, 2, 2)},
    "CG": {9: (2, 3, 2, 2)},
    "TD": {8: (2, 2, 2, 2)},
    "NG": {10: (3, 3, 4)},
    "GH": {9: (2, 3, 4)},
    "KE": {9: (3, 3, 3)},
    "ZA": {9: (2, 3, 4)},
    "MA": {9: (1, 2, 2, 2, 2)},
    "TN": {8: (2, 3, 3)},
    "DZ": {9: (1, 2, 2, 2, 2)},
    "EG": {10: (3, 3, 4)},
    "RW": {9: (3, 3, 3)},
    "UG": {9: (3, 3, 3)},
    "TZ": {9: (3, 3, 3)},
    "CD": {9: (3, 3, 3)},
    "GN": {9: (3, 2, 2, 2)},
    "MG": {9: (2, 2, 3, 2)},
    "MU": {8: (4, 4)},
}


def format_national(national: str, country_code: str) -> str:
    """Groupe les chiffres selon l'usage du pays.

    Le repli — paires de deux — est celui de la zone franc, notre marché principal.
    """
    groups = _GROUPING.get(country_code, {}).get(len(national))
    if not groups:
        groups = tuple([2] * (len(national) // 2)) + ((1,) if len(national) % 2 else ())

    out, i = [], 0
    for size in groups:
        out.append(national[i : i + size])
        i += size
    if i < len(national):
        out.append(national[i:])
    return " ".join(g for g in out if g)


def normalize(raw: str, default_country: str | None = None) -> str:
    """E.164 d'un numéro, ou chaîne vide s'il n'est pas reconnu.

    Renvoyer une chaîne vide plutôt que lever : les appelants (spec de design, fiche
    de contact) traitent l'absence de numéro comme un cas normal, et un numéro
    illisible équivaut à un numéro absent.
    """
    parsed = parse(raw, default_country)
    return parsed.e164 if parsed else ""


def extract_all(text: str, default_country: str | None = None) -> list[PhoneNumber]:
    """Tous les numéros reconnaissables d'un texte, sans doublon d'E.164.

    Utilisé par le contrôle anti-invention : le site généré ne doit afficher aucun
    numéro qui ne figure pas dans la spécification.
    """
    seen: dict[str, PhoneNumber] = {}
    for match in CANDIDATE_RE.finditer(text or ""):
        dial, body = match.group(1), match.group(2)
        candidate = f"+{dial}{body}" if dial else body
        parsed = parse(candidate, default_country)
        if parsed:
            seen.setdefault(parsed.e164, parsed)
    return list(seen.values())


def extract_emails(text: str) -> list[str]:
    """Adresses e-mail d'un texte, en minuscules et sans doublon."""
    seen: list[str] = []
    for match in EMAIL_RE.finditer(text or ""):
        value = match.group(0).lower()
        if value not in seen:
            seen.append(value)
    return seen


def whatsapp_url(raw: str, default_country: str | None = None, message: str = "") -> str:
    """Lien WhatsApp d'un numéro, ou chaîne vide si le numéro n'est pas exploitable."""
    parsed = parse(raw, default_country)
    return parsed.whatsapp_url(message) if parsed else ""
