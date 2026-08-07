"""Vérifications déterministes d'un site généré face à son DesignSpec.

Ce module a deux usages, volontairement servis par le même code :

1. **Garde-fou de l'agent codeur** — `build_site` rejette et relance une génération
   qui viole ces règles, en renvoyant au modèle la liste précise des manquements.
2. **Métrique d'évaluation** — le harnais `evals/` mesure le taux de conformité sans
   réimplémenter les règles, ce qui évite que mesure et garde-fou divergent.

Les règles reprennent les contraintes déjà écrites dans le prompt de l'agent codeur
(`app/agents/coder.py`) : autonomie totale, structure valide, fidélité au spec, et
interdiction absolue d'inventer un contact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.africa import phone as phonelib
from app.contracts import DesignSpec, GeneratedSite
from app.devsecops.sast import sast_scan


@dataclass(frozen=True)
class Issue:
    """Un manquement constaté. `code` est stable, `message` est destiné au modèle."""

    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - confort de log
        return f"[{self.code}] {self.message}"


# La reconnaissance des numéros est déléguée à `app.africa.phone`, qui connaît les
# plans de numérotation des pays desservis. L'expression régulière précédente ne
# reconnaissait que le format français : un « +229 01 97 00 00 00 » inventé par le
# modèle passait le garde-fou sans être vu, et un numéro béninois légitimement fourni
# par le client n'était pas reconnu comme tel.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_TAG_RE = re.compile(r"<[^>]+>")


def validate_site(site: GeneratedSite, spec: DesignSpec) -> list[Issue]:
    """Retourne la liste des manquements du site face au spec (vide = conforme).

    Le spec passé doit être le spec **effectif** de la génération : lors d'une refonte,
    c'est le nouveau spec, jamais l'ancien — sinon une refonte légitime serait rejetée
    pour infidélité à une palette qu'on vient justement de remplacer.
    """
    issues: list[Issue] = []
    _check_structure(site.html, issues)
    _check_asset_refs(site.html, issues)
    _check_sections(site.html, spec, issues)
    _check_palette(site.css, spec, issues)
    _check_autonomy(site.html, site.css, issues)
    _check_invented_contact(site.html, spec, issues)
    _check_regional_rules(site.html, spec, issues)
    _check_no_critical(site, issues)
    return issues


def _check_structure(html: str, issues: list[Issue]) -> None:
    if "<!doctype" not in html.lower():
        issues.append(Issue("doc.doctype", "Le document ne commence pas par <!DOCTYPE html>."))
    if not re.search(r"<html[^>]+lang\s*=", html, re.IGNORECASE):
        issues.append(Issue("doc.lang", "La balise <html> n'a pas d'attribut lang."))
    if not re.search(r"<meta[^>]+charset", html, re.IGNORECASE):
        issues.append(Issue("doc.charset", "La balise <meta charset=\"utf-8\"> est absente."))
    if not re.search(r"<meta[^>]+viewport", html, re.IGNORECASE):
        issues.append(Issue("doc.viewport", "La meta viewport est absente : le site ne sera pas responsive."))


def _check_asset_refs(html: str, issues: list[Issue]) -> None:
    if "style.css" not in html:
        issues.append(Issue("refs.stylesheet", "Le HTML ne référence pas style.css (le CSS doit être externe)."))
    if "script.js" not in html:
        issues.append(Issue("refs.script", "Le HTML ne référence pas script.js (le JS doit être externe)."))


def _check_sections(html: str, spec: DesignSpec, issues: list[Issue]) -> None:
    present = {m.group(1) for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', html)}
    for section in spec.sections:
        if section.id and section.id not in present:
            issues.append(
                Issue(
                    f"sections.missing:{section.id}",
                    f"La section « {section.title or section.id} » du spec est absente "
                    f"(aucun élément id=\"{section.id}\").",
                )
            )


def _check_palette(css: str, spec: DesignSpec, issues: list[Issue]) -> None:
    lowered = css.lower()
    for field_name in ("primary", "bg", "text"):
        color = getattr(spec.palette, field_name, "") or ""
        if color and color.lower() not in lowered:
            issues.append(
                Issue(
                    f"palette.{field_name}",
                    f"La couleur {field_name} du spec ({color}) n'apparaît pas dans le CSS.",
                )
            )


def _check_autonomy(html: str, css: str, issues: list[Issue]) -> None:
    if re.search(r"<script[^>]+src\s*=\s*[\"'](?:https?:)?//", html, re.IGNORECASE):
        issues.append(Issue("external.script", "Le HTML charge un script distant : le site doit être autonome."))
    if re.search(r"<link[^>]+href\s*=\s*[\"'](?:https?:)?//", html, re.IGNORECASE):
        issues.append(Issue("external.link", "Le HTML charge une ressource distante (CDN ou police)."))
    if re.search(r"@import\s+(?:url\()?[\"']?(?:https?:)?//", css, re.IGNORECASE):
        issues.append(Issue("external.css_import", "Le CSS importe une feuille distante."))


def _visible_text(html: str) -> str:
    """Texte affiché, hors balises : c'est là qu'un contact inventé serait visible."""
    without_code = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    return _TAG_RE.sub(" ", without_code)


def _check_invented_contact(html: str, spec: DesignSpec, issues: list[Issue]) -> None:
    """Un contact absent du spec ne doit jamais apparaître dans le site.

    C'est la règle la plus grave pour un client réel : un faux numéro sur un site
    vitrine en production envoie ses prospects chez quelqu'un d'autre — ou, pire, chez
    un concurrent.

    La comparaison se fait sur la forme E.164 et non sur le texte : le spec porte
    « 97 00 00 00 » et le site affiche « +229 97 00 00 00 ». Comparer les chaînes
    signalerait ce numéro parfaitement légitime comme inventé, et le garde-fou se
    retournerait contre les sites conformes.
    """
    text = _visible_text(html)
    haystack = f"{text}\n{html}"

    autorises = {
        parsed.e164
        for raw in (spec.contact.phone, spec.contact.whatsapp)
        if raw.strip() and (parsed := phonelib.parse(raw, spec.country))
    }
    for found in phonelib.extract_all(text, spec.country):
        if found.e164 not in autorises:
            issues.append(
                Issue(
                    "contact.invented_phone",
                    f"Un numéro de téléphone ({found.international()}) apparaît alors que le "
                    "spec ne le fournit pas.",
                )
            )
            break

    if not spec.contact.email.strip():
        for candidate in _EMAIL_RE.finditer(haystack):
            issues.append(
                Issue(
                    "contact.invented_email",
                    f"Une adresse email ({candidate.group(0)}) apparaît alors que le spec n'en fournit aucune.",
                )
            )
            break


def _check_regional_rules(html: str, spec: DesignSpec, issues: list[Issue]) -> None:
    """Contrôles propres au marché africain, tous vérifiables sans modèle.

    Ces règles ne relèvent pas du goût : un site vitrine dont le bouton WhatsApp
    manque perd la majorité de ses prises de contact, et un lien `wa.me` mal formé
    ouvre l'application sur un écran vide — que l'utilisateur lit comme un site cassé.
    """
    whatsapp = phonelib.parse(spec.contact.whatsapp, spec.country) if spec.contact.whatsapp.strip() else None
    if whatsapp:
        if "wa.me/" not in html:
            issues.append(
                Issue(
                    "africa.whatsapp_missing",
                    "Un numéro WhatsApp est fourni mais aucun lien wa.me n'apparaît : "
                    "c'est le premier canal de contact sur ce marché.",
                )
            )
        else:
            attendu = whatsapp.e164.lstrip("+")
            if f"wa.me/{attendu}" not in html:
                issues.append(
                    Issue(
                        "africa.whatsapp_format",
                        f"Le lien wa.me n'utilise pas le numéro E.164 attendu (wa.me/{attendu}). "
                        "Tout autre format ouvre WhatsApp sur une recherche vide.",
                    )
                )

    tel = phonelib.parse(spec.contact.phone, spec.country) if spec.contact.phone.strip() else None
    if tel and f"tel:{tel.e164}" not in html:
        issues.append(
            Issue(
                "africa.tel_link",
                f"Le clic-pour-appeler est absent ou mal formé : attendu tel:{tel.e164}.",
            )
        )

    # Le franc CFA n'a pas de décimales : « 15 000,00 FCFA » n'existe pas et signale
    # un formatage recopié d'un marché européen.
    if spec.commerce.currency in {"XOF", "XAF"} and re.search(r"\d[,.]\d{2}\s*(?:FCFA|XOF|XAF)", html):
        issues.append(
            Issue(
                "africa.currency_decimals",
                "Un montant en FCFA est affiché avec des décimales. Le franc CFA n'en a pas : "
                "écrire « 15 000 FCFA ».",
            )
        )


def _check_no_critical(site: GeneratedSite, issues: list[Issue]) -> None:
    for finding in sast_scan(html=site.html, css=site.css, js=site.js):
        if finding["severity"] == "critical":
            issues.append(
                Issue(
                    "sast.critical",
                    f"Vulnérabilité critique détectée : {finding['title']} ({finding.get('file', '')}).",
                )
            )
            break
