"""Endpoints agents (appelés par les workflows n8n de Caleb).

Auth : JWT utilisateur OU clé INTERNAL_API_KEY (service). L'ordre attendu est
code → review → deploy, validé par la présence des artefacts requis.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app import db
from app.contracts import (
    AgentCodeRequest,
    AgentCodeResponse,
    AgentReviewRequest,
    AgentReviewResponse,
)
from app.security import ServiceOrUser
from app.services import run_code_step, run_review_step

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _authorize(session_id: str, actor: dict | None) -> dict:
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session introuvable.")
    if actor is not None and session["user_id"] != actor["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cette session.")
    return session


@router.post("/code", response_model=AgentCodeResponse, status_code=status.HTTP_201_CREATED)
async def agent_code(payload: AgentCodeRequest, actor: ServiceOrUser) -> AgentCodeResponse:
    session = _authorize(payload.session_id, actor)
    # On archive le design spec produit par le designer n8n de Caleb, numéroté comme la
    # version de site qu'il va produire : un second appel sur la même session conserve
    # ainsi le spec précédent au lieu d'entrer en collision avec lui.
    next_version = db.latest_version(payload.session_id, "site") + 1
    db.add_artifact(payload.session_id, "design_spec", next_version, payload.design_spec.model_dump())
    version = await run_code_step(
        payload.session_id,
        session["slug"],
        payload.design_spec,
        instruction=payload.instruction,
    )
    return AgentCodeResponse(
        slug=session["slug"],
        version=version,
        files={"index.html": f"sites/{session['slug']}/v{version}/index.html", "version": str(version)},
    )


@router.post("/review", response_model=AgentReviewResponse)
async def agent_review(payload: AgentReviewRequest, actor: ServiceOrUser) -> AgentReviewResponse:
    session = _authorize(payload.session_id, actor)
    version = db.latest_version(payload.session_id, "site")
    if version == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Site non généré (appelez /api/agents/code d'abord).")
    report = await run_review_step(payload.session_id, session["slug"], version)
    return AgentReviewResponse(slug=session["slug"], report=report)
