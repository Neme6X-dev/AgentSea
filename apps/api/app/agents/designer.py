"""Choix du designer : n8n s'il répond, mini-designer interne sinon.

Un seul point d'entrée pour tout le pipeline, afin que la question « qui a produit ce
DesignSpec ? » se tranche à un seul endroit — et que la réponse remonte jusqu'à
l'interface, où l'utilisateur voit quel designer a réellement travaillé.
"""
from __future__ import annotations

import re

from app.agents import designer_mini, designer_n8n, templates
from app.contracts import DesignSpec

# Le workflow n8n nomme ses pages en français courant ; le codeur et la validation
# attendent des identifiants de section stables, dont `hero` pour l'accueil.
PAGE_TO_SECTION = {
    "accueil": "hero",
    "home": "hero",
    "index": "hero",
    "a-propos": "apropos",
    "à propos": "apropos",
    "a propos": "apropos",
    "about": "apropos",
    "histoire": "apropos",
    "menu": "services",
    "carte": "services",
    "services": "services",
    "prestations": "services",
    "boutique": "services",
    "portfolio": "portfolio",
    "realisations": "portfolio",
    "galerie": "portfolio",
    "temoignages": "temoignages",
    "avis": "temoignages",
    "equipe": "equipe",
    "contact": "contact",
    "reservation": "contact",
    "contact-reservation": "contact",
}


def _section_id(page: str) -> str:
    """Identifiant de section pour une page nommée par n8n.

    Les slugs réels sont rédigés pour le référencement, pas pour nous
    (`menu-gastronomique-africain`, `contact-reservations`). Une correspondance exacte
    les manquerait tous : on reconnaît donc le mot-clé porteur, et on ne slugifie qu'en
    dernier recours.
    """
    key = (
        page.strip().lower()
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace("à", "a").replace("ô", "o").replace("û", "u").replace("ç", "c")
    )
    if key in PAGE_TO_SECTION:
        return PAGE_TO_SECTION[key]

    # L'ordre compte : « contact-reservations » doit donner `contact`, et le premier
    # mot-clé rencontré dans cette liste l'emporte.
    for mot, section in PAGE_TO_SECTION.items():
        if mot in key:
            return section

    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return slug or "section"


# Coordonnées visibles dans le contenu produit par n8n. Elles doivent être reportées
# dans le spec : la validation rejette tout téléphone ou email présent dans le site mais
# absent du spec — garde-fou contre les contacts inventés.
PHONE_RE = re.compile(r"(?:\+33\s?|0)\d(?:[\s.\-]?\d{2}){4}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ADDRESS_RE = re.compile(r"\d{1,4}\s+(?:rue|avenue|boulevard|place|impasse|chemin)[^\n,]*,?\s*\d{5}\s+[A-ZÉÈ][\wÀ-ÿ'-]*", re.I)


def _page_text(page: dict) -> str:
    """Texte exploitable d'une fiche de page n8n."""
    return "\n".join(
        str(page.get(key, "")) for key in ("h1", "contenu", "title_tag", "meta_description")
    )


def _contact_from_pages(pages: list[dict]) -> dict[str, str]:
    """Relève les coordonnées que le contenu affichera réellement."""
    blob = "\n".join(_page_text(p) for p in pages)
    phone = PHONE_RE.search(blob)
    email = EMAIL_RE.search(blob)
    address = ADDRESS_RE.search(blob)
    return {
        "phone": phone.group(0).strip() if phone else "",
        "email": email.group(0).strip() if email else "",
        "address": address.group(0).strip() if address else "",
        "hours": "",
    }


async def spec_from_plan(brief: str, plan: dict) -> DesignSpec:
    """Compose un DesignSpec à partir de la décision du designer n8n.

    n8n ne rend pas un spec complet : il choisit un `template_id` et une liste de
    `pages`. Le contenu rédactionnel, la palette et la typographie restent à produire —
    c'est le designer interne qui s'en charge, en respectant ce que n8n a tranché.
    """
    fiche = templates.by_id(plan.get("template_id", ""))
    pages = plan.get("pages") or []

    consignes = [f"## Brief issu du cadrage\n{brief}"]
    if fiche:
        consignes.append(
            f"## Template retenu par le designer — {fiche['id']}\n"
            f"Secteur : {fiche.get('secteur', '')}\nStyle : {fiche.get('style', '')}\n"
            f"{fiche.get('description', '')}\n"
            f"Composants attendus : {', '.join(fiche.get('composants') or [])}"
        )
    if pages:
        # Le contenu rédactionnel des fiches est donné au designer : c'est de là qu'il
        # tire le nom de l'enseigne, le ton et la palette. Le réécrire perdrait ce qui
        # a été construit avec l'utilisateur pendant tout l'entretien.
        detail = "\n\n".join(
            f"### {p.get('nom') or p.get('slug') or 'Page'}\n{_page_text(p)[:1200]}" for p in pages
        )
        consignes.append(
            "## Pages et contenus décidés par le designer\n"
            f"{detail}\n\n"
            "Ces sections sont imposées. Déduis-en le nom exact de l'enseigne, le ton et "
            "une palette cohérente ; ne remplace pas les contenus."
        )

    spec = await designer_mini.build_design_spec("\n\n".join(consignes))

    # Les pages tranchées par n8n font autorité : le modèle a pu en oublier ou en
    # ajouter, or c'est cette liste que l'utilisateur a validée en conversation.
    if pages:
        sections = []
        for order, page in enumerate(pages):
            libelle = str(page.get("slug") or page.get("nom") or "")
            sections.append(
                {
                    "id": _section_id(libelle),
                    "title": str(page.get("nom") or libelle).strip() or "Section",
                    # Le contenu vient de n8n, pas du modèle : c'est le texte validé.
                    "content": str(page.get("contenu") or page.get("h1") or ""),
                    "order": order,
                }
            )
        if "hero" not in {s["id"] for s in sections}:
            sections.insert(0, {"id": "hero", "title": "Accueil", "content": "", "order": 0})
            for order, section in enumerate(sections):
                section["order"] = order

        maj: dict = {"sections": sections}

        # Un appel à l'action explicite prime sur celui qu'aurait imaginé le modèle.
        premier_cta = next((p.get("cta") for p in pages if p.get("cta")), None)
        if isinstance(premier_cta, list) and premier_cta:
            maj["cta"] = str(premier_cta[0])
        elif isinstance(premier_cta, str) and premier_cta.strip():
            maj["cta"] = premier_cta.strip()

        # Coordonnées : si le contenu en affiche, le spec doit les porter, sinon la
        # validation les signalera comme inventées et fera chuter la note.
        contact = _contact_from_pages(pages)
        if any(contact.values()):
            maj["contact"] = {**spec.contact.model_dump(), **{k: v for k, v in contact.items() if v}}

        # On repasse par le modèle plutôt que d'assigner : les sections sont revalidées
        # au même titre que si elles venaient du designer.
        spec = DesignSpec.model_validate({**spec.model_dump(), **maj})

    return spec


async def build_design_spec(
    prompt: str,
    *,
    previous: DesignSpec | None = None,
    session_id: str | None = None,
) -> tuple[DesignSpec, str]:
    """Retourne le spec et la source qui l'a produit (`"n8n"` ou `"interne"`).

    Une refonte part toujours du designer interne : lui seul reçoit le spec actuel en
    contexte, ce qui garantit que le nom et les coordonnées survivent au changement de
    style. n8n, qui ne connaît pas la session, recréerait un site pour une autre marque.
    """
    if previous is None:
        spec = await designer_n8n.build_design_spec(prompt, session_id=session_id)
        if spec is not None:
            return spec, "n8n"

    return await designer_mini.build_design_spec(prompt, previous=previous), "interne"
