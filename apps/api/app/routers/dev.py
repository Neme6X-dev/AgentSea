"""Génération complète — le chemin qu'emprunte le front.

La génération est **asynchrone** : l'appel rend la main dès la session créée, et le
pipeline (design → code → review) est confié à la file de travaux. C'est ce qui permet
au front de suivre l'avancement réel en interrogeant `GET /api/sessions/{id}` : un
appel synchrone ne rendant la main qu'à la fin, il n'y aurait rien à afficher pendant
la minute de travail, et la scène des agents ne pourrait qu'être simulée.

La génération ne publie jamais d'elle-même : elle s'arrête à `ready`, une fois la
version prête à être prévisualisée. La mise en ligne reste un geste explicite de
l'utilisateur, via `/api/sessions/{id}/publish` — sans quoi un premier essai anodin se
retrouverait en ligne sans que personne ne l'ait décidé.

En orchestration n8n complète, la même séquence est pilotée pas à pas via
/api/agents/*.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status

from app import db, jobs
from app.analytics import events
from app.billing import quotas
from app.contracts import GenerateRequest, SessionView
from app.jobs import queue
from app.security import CurrentUser
from app.services import build_session_view

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/generate", response_model=SessionView, status_code=status.HTTP_202_ACCEPTED)
async def dev_generate(payload: GenerateRequest, user: CurrentUser, request: Request) -> SessionView:
    """Ouvre une session et confie la génération à la file de travaux.

    Retourne immédiatement la session à l'état `pending` : le front la suit ensuite par
    `GET /api/sessions/{id}` jusqu'à un statut terminal (`ready`, `deployed` ou `error`).

    Les deux quotas sont vérifiés **avant** de créer la session : dépasser son forfait
    ne doit pas laisser derrière soi une session orpheline que l'utilisateur verrait
    apparaître, vide, dans sa liste de projets.
    """
    period = quotas.current_period()
    quotas.check_sites(user["plan"], db.count_sessions(user["id"], active_only=True)).raise_if_denied()
    generations = quotas.check_generations(user["plan"], db.get_usage(user["id"], "generations", period))
    if not generations.allowed:
        events.track(
            events.QUOTA_HIT, user_id=user["id"], country=user.get("country"),
            props={"resource": "generations", "plan": user["plan"]},
        )
    generations.raise_if_denied()

    # Le slug se déduit du prompt : sur un cadrage conversationnel, le nom retenu est
    # plus fidèle que la première phrase de l'utilisateur.
    label = payload.design_spec.name if payload.design_spec else payload.prompt
    slug = db.allocate_slug(label)
    country = (
        payload.country
        or (payload.design_spec.country if payload.design_spec else None)
        or user.get("country")
        or "BJ"
    ).upper()
    session_id = db.create_session(user["id"], payload.prompt, slug, country=country)

    db.update_step(session_id, "design", "running", "Analyse de la demande par le designer")
    db.increment_usage(user["id"], "generations", period)

    job_id = jobs.submit(
        queue.KIND_GENERATE,
        {
            "session_id": session_id,
            "slug": slug,
            "prompt": payload.prompt,
            "design_spec": payload.design_spec.model_dump() if payload.design_spec else None,
        },
        user_id=user["id"],
        session_id=session_id,
        priority=quotas.queue_priority(user["plan"]),
    )

    events.track(
        events.SITE_CREATED,
        user_id=user["id"], session_id=session_id, country=country,
        props={"plan": user["plan"], "from_chat": payload.design_spec is not None},
        ip=request.client.host if request.client else None,
    )
    logger.info(
        "Génération demandée : session=%s slug=%s job=%s", session_id, slug, job_id,
        extra={"session_id": session_id, "job_id": job_id, "country": country},
    )

    return build_session_view(db.get_session(session_id))
