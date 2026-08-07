"""Services partagés : étapes du pipeline (code → review → deploy) et vue de session."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import db
from app.agents import coder, reviewer
from app.config import settings
from app.contracts import (
    DesignSpec,
    GeneratedSite,
    ReviewReport,
    SessionView,
    VersionPreview,
)
from app.deploy import deploy_local, deploy_vps, version_dir, write_site_files
from app.devsecops.report import render_markdown
from app.gemini import attribute_calls


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #
def load_site_version(slug: str, version: int) -> GeneratedSite:
    d = version_dir(slug, version)
    return GeneratedSite(
        html=(d / "index.html").read_text(encoding="utf-8"),
        css=(d / "style.css").read_text(encoding="utf-8"),
        js=(d / "script.js").read_text(encoding="utf-8"),
    )


def _owner_of(session_id: str) -> int | None:
    """Propriétaire d'une session, pour attribuer un coût d'appel à un compte."""
    session = db.get_session(session_id)
    return session.get("user_id") if session else None


def get_latest_design_spec(session_id: str) -> DesignSpec | None:
    for art in reversed(db.get_artifacts(session_id, "design_spec")):
        payload = art["payload"]
        if isinstance(payload, dict) and "name" in payload:
            try:
                return DesignSpec.model_validate(payload)
            except Exception:
                continue
    return None


# --------------------------------------------------------------------------- #
# Étapes
# --------------------------------------------------------------------------- #
async def run_code_step(
    session_id: str,
    slug: str,
    spec: DesignSpec,
    *,
    instruction: str | None = None,
    model: str | None = None,
    redesign: bool = False,
) -> int:
    """Exécute l'agent codeur et écrit la nouvelle version. Retourne le numéro de version.

    Args:
        redesign: refonte complète. Le site actuel n'est alors **pas** transmis au
            codeur : le lui donner en contexte le pousse à recopier le design qu'on
            cherche justement à remplacer.
    """
    db.update_step(session_id, "code", "running", "Génération du code par l'agent codeur")
    # Rattache les appels au modèle à cette session : c'est ce qui permet au
    # back-office de dire ce qu'a coûté *ce* site plutôt qu'une moyenne globale.
    attribute_calls(agent="coder", session_id=session_id, user_id=_owner_of(session_id))
    current_site = None
    if instruction and not redesign:
        latest_art = db.get_artifacts(session_id, "site")
        if latest_art:
            current_site = load_site_version(slug, latest_art[-1]["version"])

    site = await coder.build_site(
        spec,
        instruction=instruction,
        current_site=current_site,
        model=model or settings.gemini_coder_model,
    )
    version = db.latest_version(session_id, "site") + 1
    write_site_files(slug, version, site)
    db.add_artifact(
        session_id,
        "site",
        version,
        {
            "version": version,
            "files": ["index.html", "style.css", "script.js"],
            "dir": f"sites/{slug}/v{version}",
        },
    )
    db.update_step(session_id, "code", "done", f"Version v{version} générée")
    return version


async def run_review_step(session_id: str, slug: str, version: int, model: str | None = None) -> ReviewReport:
    """Exécute l'agent review/sécurité sur une version donnée."""
    db.update_step(session_id, "review", "running", "Revue qualité et sécurité")
    attribute_calls(agent="reviewer", session_id=session_id, user_id=_owner_of(session_id))
    site = load_site_version(slug, version)
    spec = get_latest_design_spec(session_id) or DesignSpec(name=slug)
    report = await reviewer.review_site(site, spec, model=model or settings.gemini_reviewer_model)
    db.add_artifact(session_id, "report", version, report.model_dump())
    db.update_step(
        session_id,
        "review",
        "done",
        f"Score {report.score}/100 — verdict {report.verdict} ({len(report.findings)} findings)",
    )
    return report


def mark_ready(session_id: str, version: int) -> None:
    """Termine un pipeline (génération, édition, retry) sans publier.

    Statut terminal — sans lui, le front continuerait d'interroger une session dont le
    travail est pourtant fini (cf. `TERMINAL_STATUSES` côté front). La mise en ligne
    reste un geste explicite de l'utilisateur, via `run_deploy_step` / `/publish`.
    """
    db.update_step(
        session_id,
        "preview",
        "done",
        f"v{version} prête à prévisualiser — publiez-la pour la mettre en ligne.",
    )
    db.set_session_field(session_id, status="ready", current_step="preview")


async def run_deploy_step(session_id: str, slug: str, version: int) -> str:
    """Publie une version donnée (local, ou VPS si configuré) et passe la session en 'deployed'.

    `version` est réellement honorée : publier une version antérieure est le mécanisme
    de retour arrière offert au front.
    """
    db.update_step(session_id, "deploy", "running", f"Publication de la v{version}")
    try:
        if settings.vps_configured:
            deploy_local(slug, version)  # prépare live/ avec la bonne version
            url = deploy_vps(slug)
        else:
            url = deploy_local(slug, version)
        target = "vps" if settings.vps_configured else "local"
    except Exception as exc:  # pragma: no cover - dépend de l'infra
        db.update_step(session_id, "deploy", "failed", f"Déploiement échoué: {exc}")
        raise
    db.add_artifact(session_id, "deploy", version, {"target": target, "url": url, "version": version})
    # `published_at` n'est renseigné qu'à la première mise en ligne : c'est la date
    # d'activation du site, celle qui compte dans l'entonnoir et les cohortes. La
    # remettre à jour à chaque republication ferait glisser tout l'historique.
    current = db.get_session(session_id) or {}
    fields: dict[str, Any] = {"status": "deployed", "site_url": url, "current_step": "deploy"}
    if not current.get("published_at"):
        fields["published_at"] = datetime.now(timezone.utc)
    db.set_session_field(session_id, **fields)
    db.update_step(session_id, "deploy", "done", f"v{version} publiée ({target}) : {url}")
    return url


def published_version(session_id: str) -> int | None:
    """Version actuellement en ligne, déduite des artefacts de déploiement.

    Se lit dans l'historique plutôt que dans une colonne dédiée : aucune migration de
    schéma n'est nécessaire, et l'information reste cohérente avec ce qui a réellement
    été publié.

    On prend le dernier artefact **écrit**, pas celui de plus haut numéro : après un
    retour arrière, la version en ligne est justement la plus ancienne.
    """
    last = db.latest_artifact(session_id, "deploy")
    if last is None:
        return None
    payload = last.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("version"), int):
        return payload["version"]
    return last.get("version")


def report_for_version(session_id: str, version: int) -> ReviewReport | None:
    for art in reversed(db.get_artifacts(session_id, "report")):
        if art["version"] == version:
            try:
                return ReviewReport.model_validate(art["payload"])
            except Exception:
                return None
    return None


# --------------------------------------------------------------------------- #
# Vue session
# --------------------------------------------------------------------------- #
def build_session_view(session: dict[str, Any]) -> SessionView:
    slug = session["slug"]
    session_id = session["id"]
    site_versions = [art["version"] for art in db.get_artifacts(session_id, "site") if art["version"]]
    versions = [f"v{v}" for v in site_versions]
    site_url = session.get("site_url")
    report = None
    reports = db.get_artifacts(session_id, "report")
    if reports:
        try:
            report = ReviewReport.model_validate(reports[-1]["payload"])
        except Exception:
            report = None

    live_version = published_version(session_id)
    base = settings.public_base_url.rstrip("/")
    previews = []
    for version in site_versions:
        version_report = report_for_version(session_id, version)
        previews.append(
            VersionPreview(
                version=version,
                url=f"{base}/sites/{slug}/v{version}/",
                score=version_report.score if version_report else None,
                verdict=version_report.verdict if version_report else None,
                published=version == live_version,
            )
        )

    return SessionView(
        id=session_id,
        slug=slug,
        prompt=session["prompt"],
        status=session["status"],
        current_step=session.get("current_step"),
        steps=session.get("steps") or [],
        versions=versions,
        site_url=site_url,
        published_version=live_version,
        previews=previews,
        report=report,
        error=session.get("error"),
        country=session.get("country") or "BJ",
        business_type=session.get("business_type"),
        queue_position=_queue_position(session),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
    )


def _queue_position(session: dict[str, Any]) -> int | None:
    """Rang du site dans la file d'attente, `None` s'il n'attend pas.

    Affiché pendant l'attente : « 3 sites avant le vôtre » se supporte, une animation
    figée sans explication beaucoup moins. La lecture est volontairement tolérante —
    une file inaccessible ne doit pas empêcher d'afficher la session elle-même.
    """
    if session.get("status") not in {"pending", "running", "queued"}:
        return None
    try:
        from app.jobs import queue

        job = queue.latest_for_session(session["id"])
        if job is None or job["status"] != queue.STATUS_QUEUED:
            return None
        return queue.position_in_queue(job["id"])
    except Exception:
        return None
