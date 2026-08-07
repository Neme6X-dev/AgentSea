"""Endpoint de déploiement (appelé par n8n après review)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app import db
from app.config import settings
from app.contracts import DeployRequest, DeployResponse
from app.security import ServiceOrUser
from app.services import run_deploy_step

router = APIRouter(prefix="/api", tags=["deploy"])


@router.post("/deploy", response_model=DeployResponse)
async def deploy(payload: DeployRequest, actor: ServiceOrUser) -> DeployResponse:
    session = db.get_session(payload.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session introuvable.")
    if actor is not None and session["user_id"] != actor["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé.")
    version = db.latest_version(payload.session_id, "site")
    if version == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Site non généré.")
    url = await run_deploy_step(payload.session_id, session["slug"], version)
    return DeployResponse(
        slug=session["slug"],
        version=version,
        target="vps" if settings.vps_configured else "local",
        url=url,
    )
