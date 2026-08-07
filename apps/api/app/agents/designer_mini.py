"""Mini-designer (fallback dev/démo) : prompt brut → DesignSpec.

En production, ce rôle est tenu par le designer n8n de Caleb. Ce module sert à
valider ton backend en autonomie et comme plan B si n8n n'est pas disponible.
"""
from __future__ import annotations

import json

from app.config import settings
from app.contracts import DesignSpec
from app.gemini import LLMError, gemini

SYSTEM_PROMPT = """# DESIGNER — Spécification design d'un site vitrine

À partir du prompt d'un utilisateur décrivant son activité, produis une spécification de design complète en JSON.

Schéma attendu (respecte-le strictement) :
{
  "name": "nom de l'entreprise/activité",
  "tagline": "phrase d'accroche courte",
  "business_type": "restaurant|cabinet|boutique|freelance|association|autre",
  "description": "2-3 phrases sur l'activité",
  "tone": "moderne|chaleureux|premium|audacieux|sobre|fun",
  "audience": "cible client en une phrase",
  "style": "minimal|moderne|premium|playful|editorial",
  "language": "fr",
  "palette": { "primary": "#hex", "secondary": "#hex", "accent": "#hex", "bg": "#hex", "text": "#hex" },
  "typography": { "heading_font": "nom générique (Georgia, serif)", "body_font": "nom générique", "base_size": "16px" },
  "sections": [ { "id": "apropos", "title": "À propos", "content": "texte", "order": 1 } ],
  "contact": { "phone": "", "email": "", "address": "", "hours": "" },
  "cta": "libellé du bouton principal"
}

Règles:
- sections choisies parmi : hero (toujours), apropos, services, portfolio, temoignages, equipe, contact.
- Ne JAMAIS inventer téléphone, email, adresse ou horaires : laisser vide si le prompt ne les donne pas.
- La palette et la typo doivent refléter le tone (premium → tons sobres et élégants, fun → couleurs vives...).
- La langue du site suit celle du prompt (français par défaut).
- Réponds UNIQUEMENT avec le JSON, sans markdown."""


async def build_design_spec(
    prompt: str,
    model: str | None = None,
    *,
    previous: DesignSpec | None = None,
) -> DesignSpec:
    """Construit un DesignSpec depuis un prompt utilisateur brut.

    Args:
        prompt: description de l'activité, ou instruction de refonte.
        previous: spec actuel lors d'une refonte. Il sert de contexte — nom, contacts et
            contenus doivent survivre au changement de style — sans que son style ni sa
            palette ne soient repris, puisque c'est précisément ce qu'on remplace.
    """
    user = (
        f"Prompt utilisateur:\n{prompt}\n\n"
        "Génère la spécification de design JSON (utilise l'id 'apropos' pour les sections et inclus hero)."
    )
    if previous is not None:
        user = (
            f"## Spécification actuelle (à refondre)\n"
            f"{json.dumps(previous.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"## Demande de refonte\n{prompt}\n\n"
            "Produis une NOUVELLE spécification : conserve le nom, les contacts et la substance "
            "des contenus, mais applique le changement demandé au style, à la palette et à la "
            "typographie. Ne recopie pas l'ancienne palette."
        )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            data = await gemini.complete_json(
                SYSTEM_PROMPT,
                user,
                model=model or settings.gemini_coder_model,
            )
            if "hero" not in {s.get("id") for s in data.get("sections", [])}:
                data.setdefault("sections", []).insert(0, {"id": "hero", "title": "Accueil", "content": "", "order": 0})
            return DesignSpec.model_validate(data)
        except (LLMError, Exception) as exc:
            last_error = exc
            user = f"{user}\n\nATTENTION : ta réponse était invalide ({exc}). Réponds uniquement avec le JSON conforme."
    raise LLMError(f"Mini-designer : échec après retries ({last_error})")
