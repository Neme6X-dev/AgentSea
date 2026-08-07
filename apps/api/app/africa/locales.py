"""Langues et conventions locales des sites générés.

Deux plans distincts, qu'il ne faut pas mélanger :

- **La langue de l'interface** de la plateforme (fr / en), choisie par l'utilisateur
  qui construit son site.
- **La langue du site généré**, qui est celle de *ses* clients à lui. Un restaurateur
  de Cotonou fait un site en français ; un hôtel de Zanzibar en anglais et swahili ;
  une boutique de Casablanca en français et arabe.

Le module fournit aussi les conventions d'écriture qui changent d'un pays à l'autre et
qu'un modèle génératif prend par défaut « à l'américaine » s'il n'a pas la consigne :
format de date, sens d'écriture, ordre des composantes d'une adresse.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.africa import countries

# Langues d'interface réellement servies. En ajouter une suppose des traductions, pas
# seulement une entrée ici — d'où une liste courte et assumée.
UI_LANGUAGES = ("fr", "en")
DEFAULT_UI_LANGUAGE = "fr"


@dataclass(frozen=True)
class Language:
    code: str
    name_native: str
    name_fr: str
    rtl: bool = False
    #: Langue de contenu seulement : on rédige des sites dedans, pas l'interface.
    content_only: bool = True


LANGUAGES: dict[str, Language] = {
    "fr": Language("fr", "Français", "Français", content_only=False),
    "en": Language("en", "English", "Anglais", content_only=False),
    "ar": Language("ar", "العربية", "Arabe", rtl=True),
    "pt": Language("pt", "Português", "Portugais"),
    "es": Language("es", "Español", "Espagnol"),
    "sw": Language("sw", "Kiswahili", "Swahili"),
    "wo": Language("wo", "Wolof", "Wolof"),
    "bm": Language("bm", "Bamanankan", "Bambara"),
    "ln": Language("ln", "Lingála", "Lingala"),
    "rw": Language("rw", "Kinyarwanda", "Kinyarwanda"),
    "am": Language("am", "አማርኛ", "Amharique"),
    "mg": Language("mg", "Malagasy", "Malgache"),
    "zu": Language("zu", "isiZulu", "Zoulou"),
    "af": Language("af", "Afrikaans", "Afrikaans"),
}


@dataclass(frozen=True)
class LocaleProfile:
    """Conventions d'écriture d'un pays, destinées au prompt de l'agent codeur."""

    country: str
    language: str
    languages: tuple[str, ...]
    rtl: bool
    date_format: str
    time_format: str
    first_day_of_week: int   # 0 = lundi
    address_order: tuple[str, ...]
    decimal_sep: str
    thousands_sep: str


def profile(country_code: str, language: str | None = None) -> LocaleProfile:
    """Conventions applicables à un site de ce pays.

    Args:
        country_code: pays du commerce.
        language: langue imposée du site. Absente, on prend la langue principale du
            pays — celle dans laquelle ses clients cherchent réellement.
    """
    country = countries.get(country_code)
    lang = (language or country.primary_language).lower()
    lang_obj = LANGUAGES.get(lang, LANGUAGES["fr"])

    # Le Maghreb et l'Égypte écrivent la date à l'anglo-saxonne quand le site est en
    # arabe, à la française quand il est en français : c'est la langue qui décide, pas
    # le pays. Partout ailleurs sur nos marchés, le jour précède le mois.
    date_format = "MM/DD/YYYY" if lang == "en" and country.region != "afrique-ouest" else "DD/MM/YYYY"

    return LocaleProfile(
        country=country.code,
        language=lang,
        languages=tuple(dict.fromkeys((lang, *country.languages))),
        rtl=lang_obj.rtl,
        date_format=date_format,
        time_format="HH:mm" if lang != "en" else "h:mm A",
        first_day_of_week=0 if lang != "en" else 6,
        address_order=("quartier", "repere", "ville", "pays"),
        decimal_sep="," if lang in {"fr", "pt", "es"} else ".",
        thousands_sep=" " if lang in {"fr", "pt"} else ",",
    )


def content_languages(country_code: str) -> list[str]:
    """Langues dans lesquelles un site de ce pays gagne à être rédigé.

    Limité à deux : au-delà, le coût de génération double sans que le trafic suive.
    """
    return list(countries.get(country_code).languages)[:2]


def business_hours_hint(country_code: str) -> str:
    """Phrase d'horaires par défaut, cohérente avec le calendrier local.

    Le repos hebdomadaire n'est pas partout le samedi et le dimanche : afficher
    « Fermé le week-end » sur un site marocain ou égyptien est simplement faux. Ce
    texte n'est qu'une suggestion — les horaires réels du client priment toujours.
    """
    country = countries.get(country_code)
    days_fr = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    open_days = [d for i, d in enumerate(days_fr) if i not in country.weekend]
    if not open_days:
        return ""
    return f"{open_days[0].capitalize()} – {open_days[-1]} : 08h00 – 18h00"


def address_hint(country_code: str) -> str:
    """Modèle d'adresse réaliste pour le pays.

    L'adressage formel (numéro + rue + code postal) est minoritaire en Afrique de
    l'Ouest : on se repère au quartier et à un point de repère. Un site qui affiche
    « 12 rue des Lilas, 75001 » pour une boutique de Cotonou ne permet à personne de
    la trouver — alors que « Carré 245, Gbégamey, en face de la pharmacie Sainte-Rita »
    y suffit.
    """
    country = countries.get(country_code)
    ville = country.major_cities[0] if country.major_cities else country.capital
    if country.region in {"afrique-ouest", "afrique-centrale"}:
        return (
            "Quartier, point de repère, ville — "
            f"ex. « Carré 245, quartier X, en face de la pharmacie, {ville} »"
        )
    if country.region == "maghreb":
        return f"Numéro, rue, quartier, ville — ex. « 12 rue Ibn Sina, Hay Riad, {ville} »"
    return f"Rue, quartier, ville, code postal — ex. « 45 Main Street, {ville} »"
