"""Catalogue de templates — références de structure pour l'agent codeur.

Les fiches de `packages/templates/catalog/*.json` décrivent des sites de référence :
secteur, style, pages et composants attendus. Elles ne sont **pas** copiées telles quelles ; elles sont
transmises au codeur comme repère de structure, pour qu'un restaurant reçoive une carte
filtrable et un cabinet une grille de services, plutôt que la même page générique à
chaque fois.

Le catalogue est chargé une fois et mis en cache : il tient dans quelques kilo-octets et
ne change pas en cours d'exécution.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from app.config import settings
from app.contracts import DesignSpec

logger = logging.getLogger(__name__)

# Le catalogue est partagé avec le front (`packages/templates/catalog`) : les mêmes
# fiches servent de repère au codeur et alimentent la galerie de démarrage côté
# interface. Dupliquer les fichiers les aurait fait diverger dès la première retouche.
TEMPLATES_DIR = settings.templates_dir

# Secteur d'une fiche → `business_type` du DesignSpec. Les deux vocabulaires viennent
# d'équipes différentes ; les rapprocher ici évite de propager la correspondance.
SECTOR_TO_BUSINESS = {
    "restauration": "restaurant",
    "hotellerie-restauration": "restaurant",
    "cabinet-corporate": "cabinet",
    "cabinet-professionnel": "cabinet",
    "e-commerce": "boutique",
}


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    """Fiches disponibles, triées par identifiant pour un choix déterministe."""
    if not TEMPLATES_DIR.is_dir():
        return ()

    fiches = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Une fiche illisible ne doit pas empêcher de générer : on s'en passe.
            logger.warning("Template %s ignoré (%s).", path.name, exc)
            continue
        if isinstance(data, dict) and data.get("id"):
            fiches.append(data)
    return tuple(fiches)


def by_id(template_id: str) -> dict | None:
    """Fiche désignée par son identifiant, `None` si inconnue.

    C'est ce que renvoie le designer n8n : il choisit le template, le backend le
    retrouve ici. Un identifiant inconnu ne doit pas faire échouer la génération —
    l'appelant compose alors sans repère.
    """
    if not template_id:
        return None
    wanted = template_id.strip().lower()
    return next((f for f in catalog() if str(f.get("id", "")).lower() == wanted), None)


def _score(fiche: dict, spec: DesignSpec) -> int:
    """Pertinence d'une fiche pour un spec. Le secteur prime sur le style."""
    score = 0
    if SECTOR_TO_BUSINESS.get(fiche.get("secteur", "")) == spec.business_type:
        score += 10
    # Le style du spec est contraint (`minimal|moderne|premium|playful|editorial`), celui
    # des fiches est libre : on se contente d'un rapprochement lexical.
    style = (fiche.get("style") or "").lower()
    if style and (style in spec.style.lower() or spec.style.lower() in style):
        score += 3
    if style and style in (spec.tone or "").lower():
        score += 2
    return score


def best_match(spec: DesignSpec) -> dict | None:
    """Fiche la plus proche du spec, ou `None` si aucune n'est pertinente.

    Un secteur qui ne correspond à rien ne doit **pas** retomber sur la première fiche
    venue : proposer une structure d'e-commerce pour une association orienterait le
    codeur à contresens. Mieux vaut le laisser composer librement.
    """
    fiches = catalog()
    if not fiches:
        return None

    best = max(fiches, key=lambda f: _score(f, spec))
    return best if _score(best, spec) >= 10 else None


def reference_block(spec: DesignSpec) -> str:
    """Bloc de référence à insérer dans le message du codeur, vide si hors sujet."""
    fiche = best_match(spec)
    if fiche is None:
        return ""

    pages = ", ".join(fiche.get("pages") or []) or "non précisées"
    composants = "\n".join(f"- {c}" for c in (fiche.get("composants") or []))
    animations = ", ".join(fiche.get("animations") or []) or "aucune imposée"

    return (
        f"## Template de référence — {fiche['id']}\n"
        f"Site reconnu du même secteur, à utiliser comme **repère de structure**.\n"
        f"Ne le recopie pas : reprends-en l'ossature et le niveau de finition, en "
        f"appliquant strictement la palette, la typographie et les contenus du DesignSpec.\n\n"
        f"Description : {fiche.get('description', '')}\n"
        f"Sections attendues : {pages}\n"
        f"Animations : {animations}\n"
        f"Composants caractéristiques :\n{composants}\n"
    )
