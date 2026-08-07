"""Ce qu'exécute réellement un travail de la file.

Les routeurs déposent, les handlers exécutent. La séparation n'est pas cosmétique :
c'est elle qui permet au même pipeline de tourner dans le processus web (mode
`inline`, en développement) ou dans un worker séparé (mode `queue`, en production)
sans qu'une seule ligne de logique métier ne change.

Chaque handler est **idempotent dans ses effets visibles** autant que possible, parce
qu'un worker tué juste avant de valider son travail verra celui-ci repris. Écrire deux
fois la même version de site sur disque est sans conséquence ; publier deux fois non
plus. Ce qui ne doit jamais arriver, en revanche, c'est qu'une reprise crée une
*nouvelle* version — d'où la vérification d'avancement en tête de `handle_generate`.
"""
from __future__ import annotations

import logging
from typing import Any

from app import db
from app.agents import designer
from app.analytics import events
from app.billing import quotas
from app.contracts import DesignSpec, EditSessionRequest
from app.services import (
    get_latest_design_spec,
    mark_ready,
    run_code_step,
    run_deploy_step,
    run_review_step,
)

logger = logging.getLogger("app.jobs.handlers")

DESIGNER_LABELS = {
    "n8n": "Spécification produite par le designer n8n",
    "interne": "Spécification produite par le designer interne (n8n indisponible)",
    "conversation": "Spécification issue du cadrage avec l'agent conversationnel",
}


async def handle_generate(payload: dict[str, Any]) -> None:
    """Pipeline complet : design → code → revue, puis arrêt à `ready`.

    La génération ne publie jamais d'elle-même. La mise en ligne reste un geste
    explicite de l'utilisateur, via `/api/sessions/{id}/publish` — sans quoi un
    premier essai anodin se retrouverait en ligne sans que personne ne l'ait décidé.
    """
    session_id = payload["session_id"]
    slug = payload["slug"]
    prompt = payload.get("prompt", "")

    session = db.get_session(session_id)
    if session is None:
        logger.warning("Session %s disparue — travail sans objet", session_id)
        return
    # Reprise après interruption : si une version existe déjà, le codeur avait fini.
    # Repartir de zéro produirait un second site facturé au client pour rien.
    if db.latest_version(session_id, "site") > 0 and session["status"] in {"ready", "deployed"}:
        logger.info("Session %s déjà aboutie — reprise ignorée", session_id)
        return

    spec_data = payload.get("design_spec")
    spec = DesignSpec.model_validate(spec_data) if spec_data else None

    db.update_step(session_id, "design", "running", "Analyse de la demande par le designer")
    if spec is None:
        spec, source = await designer.build_design_spec(prompt, session_id=session_id)
    else:
        # Le cadrage a déjà tranché : relancer un designer produirait un autre site
        # que celui qui vient d'être validé avec l'utilisateur.
        source = "conversation"
    db.update_step(session_id, "design", "done", DESIGNER_LABELS[source])
    db.add_artifact(session_id, "design_spec", 1, spec.model_dump())

    # Le pays et le secteur retenus remontent sur la session : c'est ce qui alimente
    # la ventilation géographique et sectorielle du back-office.
    db.set_session_field(session_id, country=spec.country, business_type=spec.business_type)

    version = await run_code_step(session_id, slug, spec)
    report = await run_review_step(session_id, slug, version)
    mark_ready(session_id, version)

    events.track(
        "site.generated",
        user_id=session["user_id"],
        session_id=session_id,
        country=spec.country,
        props={"version": version, "score": report.score, "verdict": report.verdict,
               "business_type": spec.business_type, "designer": source},
    )


async def handle_edit(payload: dict[str, Any]) -> None:
    """Retouche ou refonte : spec → code → revue, puis `ready`.

    La retouche ne publie jamais d'elle-même, même sur un site jamais mis en ligne.
    """
    session_id = payload["session_id"]
    slug = payload["slug"]
    request = EditSessionRequest.model_validate(payload["request"])

    current_spec = get_latest_design_spec(session_id)
    if current_spec is None:
        raise ValueError("Aucun design spec : le site doit être généré d'abord.")

    spec, redesign = await _resolve_spec(session_id, request, current_spec)
    version = await run_code_step(
        session_id, slug, spec, instruction=request.instruction, redesign=redesign
    )
    report = await run_review_step(session_id, slug, version)
    mark_ready(session_id, version)

    session = db.get_session(session_id)
    events.track(
        "site.edited",
        user_id=session["user_id"] if session else None,
        session_id=session_id,
        country=spec.country,
        props={"version": version, "mode": request.mode, "redesign": redesign, "score": report.score},
    )


async def handle_publish(payload: dict[str, Any]) -> None:
    """Met en ligne une version déjà générée."""
    session_id = payload["session_id"]
    slug = payload["slug"]
    version = int(payload["version"])

    url = await run_deploy_step(session_id, slug, version)

    session = db.get_session(session_id)
    events.track(
        "site.published",
        user_id=session["user_id"] if session else None,
        session_id=session_id,
        country=session.get("country") if session else None,
        props={"version": version, "url": url},
    )


async def handle_review(payload: dict[str, Any]) -> None:
    """Relance la revue qualité/sécurité sur une version donnée."""
    session_id = payload["session_id"]
    slug = payload["slug"]
    version = int(payload.get("version") or db.latest_version(session_id, "site"))
    if version == 0:
        raise ValueError("Aucune version à relire.")
    await run_review_step(session_id, slug, version)
    mark_ready(session_id, version)


async def _resolve_spec(
    session_id: str, payload: EditSessionRequest, current_spec: DesignSpec
) -> tuple[DesignSpec, bool]:
    """Détermine le DesignSpec effectif de l'édition, et s'il s'agit d'une refonte.

    Le spec retourné est celui contre lequel le site sera validé. C'est le point clé :
    valider une refonte contre l'ancien spec la ferait rejeter pour infidélité à une
    palette qu'on vient précisément de remplacer.
    """
    next_version = db.latest_version(session_id, "site") + 1

    # Un spec fourni vaut refonte, quel que soit le mode annoncé : c'est le designer de
    # n8n qui a tranché.
    if payload.design_spec is not None:
        db.add_artifact(session_id, "design_spec", next_version, payload.design_spec.model_dump())
        return payload.design_spec, True

    if payload.mode == "redesign":
        # Pas de spec fourni : le designer en produit un depuis l'instruction, en gardant
        # le nom et les contacts de l'ancien.
        new_spec, _ = await designer.build_design_spec(
            payload.instruction, previous=current_spec, session_id=session_id
        )
        db.add_artifact(session_id, "design_spec", next_version, new_spec.model_dump())
        return new_spec, True

    return current_spec, False


#: Aiguillage type de travail → fonction. Le worker s'y réfère et refuse tout ce qui
#: n'y figure pas, plutôt que de tenter une exécution approximative.
HANDLERS = {
    "site.generate": handle_generate,
    "site.edit": handle_edit,
    "site.publish": handle_publish,
    "site.review": handle_review,
}


def on_permanent_failure(job: dict[str, Any], error: str) -> None:
    """Ce qu'on fait quand un travail a épuisé ses tentatives.

    La session doit basculer en erreur : sans cela, le front continuerait d'interroger
    une génération qui ne reviendra jamais, et l'utilisateur resterait devant une
    animation d'attente sans fin — le pire des retours possibles.
    """
    session_id = job.get("session_id")
    if not session_id:
        return
    # L'ordre compte : `update_step` recopie le statut de l'étape sur la session dès
    # qu'il n'est pas « done ». Écrire l'étape après le statut terminal remplaçait
    # donc « error » par « failed », et le front — qui affiche le champ `error` sur
    # le statut `error` — laissait l'utilisateur devant un échec sans explication.
    db.update_step(session_id, job.get("kind", "job"), "failed", error[:500])
    db.set_session_field(
        session_id,
        status="error",
        error=f"La génération n'a pas abouti après {job.get('attempts')} tentatives. {error}"[:1000],
    )
    events.track(
        "job.failed",
        user_id=job.get("user_id"),
        session_id=session_id,
        props={"kind": job.get("kind"), "attempts": job.get("attempts"), "error": error[:200]},
    )


def consume_quota(user_id: int | None, metric: str = "generations") -> None:
    """Décompte une unité du forfait, une fois le travail réellement engagé.

    Le décompte a lieu ici et non à la mise en file : un travail rejeté faute de
    worker disponible ne doit rien coûter au client.
    """
    if user_id is None:
        return
    db.increment_usage(user_id, metric, quotas.current_period())
