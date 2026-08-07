"""Designer n8n (Caleb) : prompt utilisateur → DesignSpec, via le webhook de chat.

En production, le rôle de designer est tenu par n8n (ARCHITECTURE.md §1) : c'est lui
qui traduit la demande de l'utilisateur en `DesignSpec`, contrat d'entrée du codeur.
Ce module est le point de branchement côté backend.

Il ne lève jamais : toute panne — webhook injoignable, timeout, réponse en prose
plutôt qu'en JSON — retourne `None`, et l'appelant retombe sur `designer_mini`. C'est
le comportement voulu, pas une facilité : une génération ne doit pas échouer parce
qu'un maillon d'orchestration externe est indisponible.
"""
from __future__ import annotations

import json
import logging
import uuid

import httpx

from app.config import settings
from app.contracts import DesignSpec

logger = logging.getLogger(__name__)

# Le webhook est un agent conversationnel : sans cadrage il pose des questions au lieu
# de répondre. On lui rappelle le schéma attendu et qu'aucun texte ne doit l'entourer.
SPEC_INSTRUCTION = """[MODE MACHINE — ne pose aucune question, ne fais aucun préambule]

Produis MAINTENANT la spécification de design en JSON brut, et rien d'autre.

Schéma exact :
{
  "name": "nom de l'activité",
  "tagline": "phrase d'accroche courte",
  "business_type": "restaurant|cabinet|boutique|freelance|association|autre",
  "description": "2-3 phrases",
  "tone": "moderne|chaleureux|premium|audacieux|sobre|fun",
  "audience": "cible en une phrase",
  "style": "minimal|moderne|premium|playful|editorial",
  "language": "fr",
  "palette": {"primary": "#hex", "secondary": "#hex", "accent": "#hex", "bg": "#hex", "text": "#hex"},
  "typography": {"heading_font": "Georgia, serif", "body_font": "system-ui, sans-serif", "base_size": "16px"},
  "sections": [{"id": "hero", "title": "Accueil", "content": "texte", "order": 0}],
  "contact": {"phone": "", "email": "", "address": "", "hours": ""},
  "cta": "libellé du bouton principal"
}

Règles : ids de sections parmi hero (obligatoire), apropos, services, portfolio,
temoignages, equipe, contact. Ne JAMAIS inventer de téléphone, email, adresse ni
horaires — laisser la chaîne vide si la demande ne les fournit pas.

Demande de l'utilisateur :
"""


def _extract_json_object(text: str) -> dict | None:
    """Isole le premier objet JSON d'un texte, même noyé dans de la prose.

    Le webhook répond en langage naturel et peut encadrer le JSON de commentaires ou
    d'une clôture markdown. On balaie donc les accolades en tenant compte des chaînes
    et des échappements, plutôt que de découper sur le premier `}` venu.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _payload_to_spec_dict(payload: object) -> dict | None:
    """Ramène la réponse du webhook à un dictionnaire de spec, quelle que soit sa forme.

    n8n renvoie selon le nœud terminal : l'objet directement, `{"output": …}` avec du texte ou
    déjà du JSON, ou une liste d'items. On accepte les trois plutôt que d'imposer une
    forme au workflow de Caleb.
    """
    if isinstance(payload, list):
        payload = payload[0] if payload else None

    if isinstance(payload, dict):
        if "name" in payload:
            return payload
        for key in ("output", "text", "data", "design_spec", "designSpec", "response"):
            if key in payload:
                nested = _payload_to_spec_dict(payload[key])
                if nested is not None:
                    return nested
        return None

    if isinstance(payload, str):
        found = _extract_json_object(payload)
        return found if isinstance(found, dict) and "name" in found else None

    return None


def _extract_plan(payload: object) -> dict | None:
    """Décision du designer n8n : quel template, et quelles pages.

    C'est le contrat réel du workflow — `{"output": …, "template_id": …, "pages": […]}` —
    et non un DesignSpec complet. L'identifiant renvoie à une fiche du catalogue, les
    pages donnent les sections attendues ; le backend en compose le spec.
    """
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        return None

    template_id = payload.get("template_id") or payload.get("templateId")
    pages = payload.get("pages")

    if not template_id and not pages:
        return None

    # `pages` arrive sérialisé : le workflow renvoie un tableau JSON **dans une chaîne**.
    # Le découper naïvement sur les virgules produirait des fragments de JSON en guise
    # de noms de pages.
    if isinstance(pages, str):
        try:
            pages = json.loads(pages)
        except json.JSONDecodeError:
            pages = [p.strip() for p in pages.split(",") if p.strip()]
    if not isinstance(pages, list):
        pages = []

    # Chaque page est soit un simple nom, soit une fiche complète (slug, h1, contenu,
    # SEO). On conserve les fiches telles quelles : leur contenu rédactionnel est ce
    # que l'agent a produit avec l'utilisateur, et le réécrire le perdrait.
    normalisees = []
    for page in pages:
        if isinstance(page, dict):
            normalisees.append(page)
        elif str(page).strip():
            normalisees.append({"nom": str(page).strip()})

    return {
        "template_id": str(template_id).strip() if template_id else "",
        "pages": normalisees,
    }


async def chat(
    message: str, *, conversation_id: str
) -> tuple[str | None, DesignSpec | None, dict | None, str | None]:
    """Fait suivre un message à l'agent conversationnel n8n.

    Retourne `(réponse, spec, plan, erreur)`. L'agent mène l'entretien de cadrage —
    c'est son rôle : sans lui, un simple « bonjour » suffirait à lancer la génération
    d'un site. Il pose donc des questions jusqu'à cerner le besoin, et ce n'est
    qu'ensuite qu'un plan peut apparaître dans sa réponse.

    En cas d'échec, `réponse` est `None` et `erreur` porte une cause lisible. La
    distinction compte : un workflow en erreur, un délai dépassé et une coupure réseau
    se corrigent à trois endroits différents.
    """
    if not settings.n8n_designer_url:
        return None, None, None, "Aucune URL de workflow n8n configurée."

    body = {"action": "sendMessage", "sessionId": conversation_id, "chatInput": message}
    try:
        async with httpx.AsyncClient(timeout=settings.n8n_chat_timeout_s) as client:
            response = await client.post(settings.n8n_designer_url, json=body)
    except httpx.TimeoutException:
        logger.warning("Chat n8n : délai dépassé (%ss).", settings.n8n_chat_timeout_s)
        return None, None, None, (
            f"Le workflow n8n n'a pas répondu en {int(settings.n8n_chat_timeout_s)} s."
        )
    except Exception as exc:
        logger.warning("Chat n8n injoignable (%s).", exc)
        return None, None, None, "Le workflow n8n est injoignable (réseau)."

    # Distinguer les causes n'est pas cosmétique : une panne du workflow amont et une
    # coupure réseau appellent des actions opposées, et les confondre fait chercher le
    # problème du mauvais côté.
    if response.status_code >= 400:
        detail = response.text[:200].replace("\n", " ")
        logger.warning("Chat n8n : HTTP %s — %s", response.status_code, detail)
        if response.status_code >= 500:
            raison = (
                f"Le workflow n8n a échoué (HTTP {response.status_code} — {detail}). "
                "C'est une erreur côté workflow, pas côté backend."
            )
        else:
            raison = f"Le workflow n8n a refusé l'appel (HTTP {response.status_code})."
        return None, None, None, raison

    try:
        payload = response.json()
    except Exception as exc:
        logger.warning("Chat n8n : réponse illisible (%s).", exc)
        return None, None, None, "Le workflow n8n a renvoyé une réponse illisible."

    reply = _extract_reply(payload)
    spec_data = _payload_to_spec_dict(payload)
    spec = _validate_spec(spec_data) if spec_data is not None else None
    plan = _extract_plan(payload)

    return reply, spec, plan, None


def _extract_reply(payload: object) -> str:
    """Texte affichable de la réponse n8n, quelle que soit l'enveloppe du workflow."""
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("output", "text", "reply", "response", "message"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        # Sur le tour final, `output` est un objet (le plan de construction), pas une
        # phrase. Déverser ce JSON dans le fil de discussion n'apprendrait rien à
        # l'utilisateur : on annonce simplement que le cadrage est terminé.
        if _extract_plan(payload) is not None:
            return "J'ai tout ce qu'il me faut : je lance la construction de votre site."
        return json.dumps(payload, ensure_ascii=False)
    return ""


def _validate_spec(data: dict) -> DesignSpec | None:
    """Valide un dictionnaire de spec, en rétablissant la section `hero` si besoin."""
    # Le codeur et la revue supposent tous deux une section `hero` : la rétablir ici
    # évite de faire échouer la validation pour un oubli du workflow amont.
    if "hero" not in {s.get("id") for s in data.get("sections", []) if isinstance(s, dict)}:
        data.setdefault("sections", []).insert(0, {"id": "hero", "title": "Accueil", "content": "", "order": 0})
    try:
        return DesignSpec.model_validate(data)
    except Exception as exc:
        logger.warning("Designer n8n : spec non conforme (%s).", exc)
        return None


async def build_design_spec(prompt: str, *, session_id: str | None = None) -> DesignSpec | None:
    """Demande un DesignSpec au designer n8n. Retourne `None` si rien d'exploitable.

    `session_id` sert de fil de conversation côté n8n : en réutiliser un par session de
    génération évite que deux utilisateurs partagent la mémoire du même agent.
    """
    if not settings.n8n_designer_url:
        return None

    body = {
        "action": "sendMessage",
        "sessionId": session_id or uuid.uuid4().hex,
        "chatInput": f"{SPEC_INSTRUCTION}{prompt}",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.n8n_timeout_s) as client:
            response = await client.post(settings.n8n_designer_url, json=body)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        # 524 (timeout Cloudflare), 404, réseau coupé, corps non-JSON : même conclusion.
        logger.warning("Designer n8n indisponible (%s) — repli sur le designer interne.", exc)
        return None

    data = _payload_to_spec_dict(payload)
    if data is None:
        logger.warning("Designer n8n : réponse sans DesignSpec exploitable — repli sur le designer interne.")
        return None

    return _validate_spec(data)
