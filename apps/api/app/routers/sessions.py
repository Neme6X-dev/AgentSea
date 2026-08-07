"""Sessions : création, listing, détail, édition IA, publication, retry."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app import db, jobs
from app.analytics import events
from app.billing import quotas
from app.contracts import (
    ArtifactRecord,
    CreateSessionRequest,
    EditSessionRequest,
    PublishRequest,
    SessionCreated,
    SessionView,
)
from app.jobs import queue
from app.security import CurrentUser
from app.services import (
    build_session_view,
    get_latest_design_spec,
    report_for_version,
    run_deploy_step,
)

logger = logging.getLogger("app.sessions")

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _authorized_session(session_id: str, user: dict) -> dict:
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session introuvable.")
    if session["user_id"] != user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cette session.")
    return session


@router.post("", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
def create_session(payload: CreateSessionRequest, user: CurrentUser) -> SessionCreated:
    quotas.check_sites(user["plan"], db.count_sessions(user["id"], active_only=True)).raise_if_denied()
    slug = db.allocate_slug(payload.prompt)
    country = (payload.country or user.get("country") or "BJ").upper()
    sid = db.create_session(user["id"], payload.prompt, slug, country=country)
    return SessionCreated(id=sid, slug=slug)


@router.get("", response_model=list[SessionView])
def list_sessions(user: CurrentUser) -> list[SessionView]:
    return [build_session_view(s) for s in db.list_sessions(user["id"])]


@router.get("/{session_id}", response_model=SessionView)
def get_session(session_id: str, user: CurrentUser) -> SessionView:
    return build_session_view(_authorized_session(session_id, user))


@router.get("/{session_id}/artifacts", response_model=list[ArtifactRecord])
def list_artifacts(session_id: str, user: CurrentUser) -> list[ArtifactRecord]:
    _authorized_session(session_id, user)
    return [ArtifactRecord(**a) for a in db.get_artifacts(session_id)]


@router.post("/{session_id}/edit", response_model=SessionView, status_code=status.HTTP_202_ACCEPTED)
async def edit_session(session_id: str, payload: EditSessionRequest, user: CurrentUser) -> SessionView:
    """Confie une modification à la file et produit une nouvelle version.

    La nouvelle version s'arrête toujours à la prévisualisation (`ready`) et attend un
    appel explicite à `/publish` — y compris sur un site jamais encore publié, pour
    qu'aucune mise en ligne ne se produise sans un geste délibéré de l'utilisateur.

    Asynchrone comme `/api/dev/generate`, et pour la même raison : le front suit
    l'avancement réel des agents au lieu d'attendre devant un appel muet.
    """
    session = _authorized_session(session_id, user)
    if get_latest_design_spec(session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun design spec : générez le site d'abord.",
        )

    period = quotas.current_period()
    check = quotas.check_generations(user["plan"], db.get_usage(user["id"], "generations", period))
    if not check.allowed:
        events.track(
            events.QUOTA_HIT, user_id=user["id"], session_id=session_id,
            props={"resource": "generations", "plan": user["plan"], "action": "edit"},
        )
    check.raise_if_denied()

    versions = db.latest_version(session_id, "site")
    quotas.check_versions(user["plan"], versions).raise_if_denied()

    db.update_step(session_id, "code", "running", "Application de votre demande")
    db.increment_usage(user["id"], "generations", period)

    jobs.submit(
        queue.KIND_EDIT,
        {"session_id": session_id, "slug": session["slug"], "request": payload.model_dump()},
        user_id=user["id"],
        session_id=session_id,
        priority=quotas.queue_priority(user["plan"]),
    )

    return build_session_view(db.get_session(session_id))


@router.post("/{session_id}/publish", response_model=SessionView)
async def publish_session(session_id: str, payload: PublishRequest, user: CurrentUser) -> SessionView:
    """Met en ligne une version donnée. Publier une version antérieure = retour arrière.

    Une version au verdict `fail` n'est pas publiée sans `force` : on protège
    l'utilisateur d'une mise en ligne cassée, sans jamais lui interdire de décider.

    La publication reste **synchrone**, contrairement à la génération : elle dure
    quelques secondes et l'utilisateur attend devant le bouton. Lui rendre la main
    avant que son site soit réellement en ligne l'inviterait à ouvrir une URL qui
    n'existe pas encore.
    """
    session = _authorized_session(session_id, user)
    version = payload.version or db.latest_version(session_id, "site")
    if version == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune version générée.")

    known = {art["version"] for art in db.get_artifacts(session_id, "site")}
    if version not in known:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version v{version} inconnue pour cette session.",
        )

    report = report_for_version(session_id, version)
    failing = report is not None and report.verdict == "fail"
    if failing and not payload.force:
        blocking = [f.title for f in report.findings if f.severity in ("critical", "high")]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"La v{version} a le verdict « fail » (score {report.score}/100).",
                "score": report.score,
                "blocking_findings": blocking[:10],
                "hint": "Relancez avec force=true pour publier malgré tout.",
            },
        )

    if failing:
        # Passer outre le contrôle de sécurité est une décision, pas un détail : elle doit
        # rester lisible après coup, dans les logs comme dans l'historique de la session.
        blocking = [f.title for f in report.findings if f.severity in ("critical", "high")]
        logger.warning(
            "Publication forcée : session=%s version=%s utilisateur=%s score=%s bloquants=%s",
            session_id, version, user["id"], report.score, "; ".join(blocking[:5]) or "aucun",
        )
        db.update_step(
            session_id,
            "publish",
            "forced",
            f"v{version} publiée malgré un verdict « fail » (score {report.score}/100) — "
            f"{len(blocking)} finding(s) critique(s) ou élevé(s) ignoré(s).",
        )

    url = await run_deploy_step(session_id, session["slug"], version)
    events.track(
        events.SITE_PUBLISHED,
        user_id=user["id"], session_id=session_id, country=session.get("country"),
        props={"version": version, "url": url, "forced": bool(failing)},
    )
    return build_session_view(db.get_session(session_id))


@router.post("/{session_id}/retry", response_model=SessionView)
async def retry_session(session_id: str, user: CurrentUser) -> SessionView:
    """Relance la dernière étape en échec.

    Repasse par la file plutôt que d'exécuter sur place : une relance a exactement les
    mêmes besoins qu'une première tentative — durée, reprise après incident, priorité
    liée au forfait — et devrait sinon les réimplémenter.
    """
    session = _authorized_session(session_id, user)
    steps = session.get("steps") or []
    last_failed = next((x for x in reversed(steps) if x.get("status") == "failed"), None)
    if last_failed is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rien à relancer.")

    failed_step = last_failed["step"]
    priority = quotas.queue_priority(user["plan"])
    slug = session["slug"]

    if failed_step in {"code", "design", "site.generate"}:
        spec = get_latest_design_spec(session_id)
        if spec is None:
            db.set_session_field(session_id, status="pending", current_step=None, error=None)
            return build_session_view(db.get_session(session_id))
        db.set_session_field(session_id, status="running", error=None)
        jobs.submit(
            queue.KIND_GENERATE,
            {"session_id": session_id, "slug": slug, "prompt": session["prompt"],
             "design_spec": spec.model_dump()},
            user_id=user["id"], session_id=session_id, priority=priority,
        )
    elif failed_step in {"review", "site.review"}:
        version = db.latest_version(session_id, "site")
        if version == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Site non généré.")
        db.set_session_field(session_id, status="running", error=None)
        jobs.submit(
            queue.KIND_REVIEW,
            {"session_id": session_id, "slug": slug, "version": version},
            user_id=user["id"], session_id=session_id, priority=priority,
        )
    elif failed_step in {"deploy", "site.publish"}:
        version = db.latest_version(session_id, "site")
        await run_deploy_step(session_id, slug, version)

    return build_session_view(db.get_session(session_id))
