"""File de travaux durable, adossée à PostgreSQL.

**Pourquoi pas `asyncio.create_task`.** Le prototype lançait la génération dans une
tâche du processus web. Trois défauts, tous rencontrés dès qu'on dépasse un utilisateur :

1. Une génération dure de 60 à 180 secondes. Pendant ce temps elle occupe la boucle
   d'événements du serveur web ; quelques générations simultanées suffisent à faire
   traîner toutes les autres requêtes, y compris le *polling* qui affiche l'avancement.
2. Un redémarrage — déploiement, `OOMKilled`, coupure de courant, ce qui arrive — perd
   la tâche en vol. La session reste « en cours » indéfiniment et le front interroge
   dans le vide, sans qu'aucune erreur n'apparaisse nulle part.
3. On ne peut pas ajouter un second serveur : les tâches ne sont pas partagées.

**Pourquoi pas Redis / Celery.** Une dépendance d'infrastructure de plus à héberger,
superviser et sauvegarder, sur des VPS où chaque service compte. PostgreSQL est déjà
là, sauvegardé, et `SELECT … FOR UPDATE SKIP LOCKED` fournit exactement la primitive
nécessaire : plusieurs workers qui piochent dans la même table sans se marcher dessus,
sans verrou global et sans qu'un travail soit jamais pris deux fois.

Le jour où le volume justifie une vraie file, seul ce module change.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

from app import db
from app.config import settings

logger = logging.getLogger("app.jobs")

# Types de travaux. Le worker refuse ce qu'il ne connaît pas plutôt que de l'essayer :
# un travail inconnu vient forcément d'une version plus récente du code, et l'exécuter
# à moitié serait pire que de le laisser en attente d'un déploiement.
KIND_GENERATE = "site.generate"
KIND_EDIT = "site.edit"
KIND_PUBLISH = "site.publish"
KIND_REVIEW = "site.review"
KNOWN_KINDS = (KIND_GENERATE, KIND_EDIT, KIND_PUBLISH, KIND_REVIEW)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

#: Attente avant nouvelle tentative, par numéro de tentative. Croissance rapide :
#: la cause d'échec la plus fréquente est un quota de modèle épuisé, qui ne se libère
#: pas en dix secondes. Réessayer trop vite gaspille une tentative pour rien.
_BACKOFF_S = (30, 180, 600)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(
    kind: str,
    payload: dict[str, Any],
    *,
    user_id: int | None = None,
    session_id: str | None = None,
    priority: int = 3,
    max_attempts: int | None = None,
    delay_s: int = 0,
) -> str:
    """Dépose un travail et retourne son identifiant.

    Args:
        priority: 0 = le plus urgent. Alimenté par `billing.quotas.queue_priority`,
            pour que les comptes payants passent devant aux heures de pointe.
        delay_s: report d'exécution, pour les travaux qui doivent attendre.

    Returns:
        L'identifiant du travail, conservé sur la session afin que le front puisse
        afficher la position dans la file.
    """
    if kind not in KNOWN_KINDS:
        raise ValueError(f"Type de travail inconnu : {kind}")

    job_id = uuid.uuid4().hex[:24]
    now = _utcnow()
    with db.session_scope() as s:
        s.add(
            db.Job(
                id=job_id,
                kind=kind,
                payload=json.dumps(payload, ensure_ascii=False, default=str),
                status=STATUS_QUEUED,
                priority=priority,
                max_attempts=max_attempts or settings.job_max_attempts,
                run_at=now + timedelta(seconds=delay_s) if delay_s else now,
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
        )
    logger.info(
        "Travail déposé : %s (%s)", job_id, kind,
        extra={"job_id": job_id, "kind": kind, "session_id": session_id, "priority": priority},
    )
    return job_id


def claim(worker_id: str, kinds: tuple[str, ...] = KNOWN_KINDS) -> dict[str, Any] | None:
    """Réserve le prochain travail exécutable pour ce worker. `None` si la file est vide.

    Le cœur de la concurrence tient dans `FOR UPDATE SKIP LOCKED` : la transaction pose
    un verrou de ligne sur le candidat retenu, et tout autre worker qui lit la table au
    même instant *saute* cette ligne au lieu d'attendre. Deux workers ne peuvent donc
    jamais réserver le même travail, sans verrou global ni file en mémoire.

    L'ordre de service — priorité, puis ancienneté — fait que l'attente d'un compte
    gratuit reste bornée : à priorité égale, c'est toujours le plus ancien qui passe.
    """
    now = _utcnow()
    with db.session_scope() as s:
        row = (
            s.query(db.Job)
            .filter(
                db.Job.status == STATUS_QUEUED,
                db.Job.kind.in_(kinds),
                db.Job.run_at <= now,
            )
            .order_by(db.Job.priority.asc(), db.Job.run_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None

        row.status = STATUS_RUNNING
        row.locked_at = now
        row.locked_by = worker_id
        row.attempts += 1
        row.updated_at = now
        s.flush()
        return db._dict(row)


def complete(job_id: str, *, duration_ms: int | None = None) -> None:
    """Marque un travail comme terminé avec succès."""
    now = _utcnow()
    with db.session_scope() as s:
        s.query(db.Job).filter_by(id=job_id).update(
            {
                "status": STATUS_DONE,
                "finished_at": now,
                "updated_at": now,
                "duration_ms": duration_ms,
                "locked_by": None,
                "error": None,
            }
        )


def fail(job_id: str, error: str) -> bool:
    """Enregistre un échec et replanifie si des tentatives restent.

    Returns:
        `True` si le travail sera réessayé, `False` s'il est définitivement en échec.
        L'appelant s'en sert pour décider s'il consigne l'erreur sur la session — un
        « en cours » qui va reprendre dans trente secondes n'a pas à devenir un
        message d'erreur pour l'utilisateur.
    """
    now = _utcnow()
    with db.session_scope() as s:
        row = s.get(db.Job, job_id)
        if row is None:
            return False

        # Le message d'erreur part dans une colonne consultée depuis le back-office :
        # on tronque, sinon une trace de plusieurs kilo-octets rend la liste des
        # travaux illisible et alourdit chaque lecture.
        row.error = (error or "")[:2000]
        row.updated_at = now
        row.locked_by = None

        if row.attempts < row.max_attempts:
            delay = _BACKOFF_S[min(row.attempts - 1, len(_BACKOFF_S) - 1)]
            row.status = STATUS_QUEUED
            row.run_at = now + timedelta(seconds=delay)
            row.locked_at = None
            logger.warning(
                "Travail %s en échec (tentative %s/%s) — nouvelle tentative dans %s s",
                job_id, row.attempts, row.max_attempts, delay,
                extra={"job_id": job_id, "kind": row.kind, "attempt": row.attempts},
            )
            return True

        row.status = STATUS_FAILED
        row.finished_at = now
        logger.error(
            "Travail %s abandonné après %s tentatives : %s", job_id, row.attempts, row.error,
            extra={"job_id": job_id, "kind": row.kind, "session_id": row.session_id},
        )
        return False


def reclaim_stale(timeout_s: int | None = None) -> int:
    """Remet en file les travaux dont le worker a disparu. Retourne le nombre repris.

    C'est la contrepartie indispensable du verrou : un worker tué en plein travail
    laisse une ligne `running` que plus personne ne touchera. Sans cette reprise, la
    promesse « le travail survit au processus » serait fausse.

    Le seuil doit rester largement supérieur à la plus longue génération, sinon on
    reprendrait un travail toujours en cours et le client recevrait deux sites.
    """
    limit = _utcnow() - timedelta(seconds=timeout_s or settings.job_lock_timeout_s)
    now = _utcnow()
    with db.session_scope() as s:
        stale = (
            s.query(db.Job)
            .filter(db.Job.status == STATUS_RUNNING, db.Job.locked_at < limit)
            .all()
        )
        for row in stale:
            if row.attempts >= row.max_attempts:
                row.status = STATUS_FAILED
                row.error = "Worker interrompu et tentatives épuisées."
                row.finished_at = now
            else:
                row.status = STATUS_QUEUED
                row.run_at = now
                row.locked_at = None
                row.locked_by = None
                row.error = "Worker interrompu — travail repris."
            row.updated_at = now
        if stale:
            logger.warning("%s travail(x) orphelin(s) repris", len(stale))
        return len(stale)


def get(job_id: str) -> dict[str, Any] | None:
    with db.session_scope() as s:
        row = s.get(db.Job, job_id)
        return db._dict(row) if row else None


def latest_for_session(session_id: str) -> dict[str, Any] | None:
    with db.session_scope() as s:
        row = (
            s.query(db.Job)
            .filter_by(session_id=session_id)
            .order_by(db.Job.created_at.desc())
            .first()
        )
        return db._dict(row) if row else None


def position_in_queue(job_id: str) -> int:
    """Nombre de travaux servis avant celui-ci. 0 = le prochain.

    Affiché à l'utilisateur pendant l'attente : « 3 sites avant le vôtre » est une
    information qu'on supporte, là où une barre de progression figée inquiète.
    """
    with db.session_scope() as s:
        row = s.get(db.Job, job_id)
        if row is None or row.status != STATUS_QUEUED:
            return 0
        return (
            s.query(db.Job)
            .filter(
                db.Job.status == STATUS_QUEUED,
                db.Job.run_at <= _utcnow(),
                (db.Job.priority < row.priority)
                | ((db.Job.priority == row.priority) & (db.Job.run_at < row.run_at)),
            )
            .count()
        )


def stats() -> dict[str, Any]:
    """État de la file, pour la supervision du back-office."""
    with db.session_scope() as s:
        by_status = dict(
            s.query(db.Job.status, func.count(db.Job.id)).group_by(db.Job.status).all()
        )
        oldest = (
            s.query(func.min(db.Job.run_at))
            .filter(db.Job.status == STATUS_QUEUED, db.Job.run_at <= _utcnow())
            .scalar()
        )
        avg_ms = (
            s.query(func.avg(db.Job.duration_ms))
            .filter(db.Job.status == STATUS_DONE, db.Job.duration_ms.isnot(None))
            .scalar()
        )
        workers = (
            s.query(func.count(func.distinct(db.Job.locked_by)))
            .filter(db.Job.status == STATUS_RUNNING)
            .scalar()
        )

    wait_s = int((_utcnow() - oldest).total_seconds()) if oldest else 0
    return {
        "queued": int(by_status.get(STATUS_QUEUED, 0)),
        "running": int(by_status.get(STATUS_RUNNING, 0)),
        "done": int(by_status.get(STATUS_DONE, 0)),
        "failed": int(by_status.get(STATUS_FAILED, 0)),
        "oldest_wait_s": max(0, wait_s),
        "avg_duration_ms": int(avg_ms or 0),
        "active_workers": int(workers or 0),
    }


def list_jobs(
    *, status: str | None = None, kind: str | None = None, limit: int = 25, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Travaux filtrés et leur total, pour l'écran d'exploitation."""
    with db.session_scope() as s:
        q = s.query(db.Job)
        if status:
            q = q.filter(db.Job.status == status)
        if kind:
            q = q.filter(db.Job.kind == kind)
        total = q.count()
        rows = q.order_by(db.Job.created_at.desc()).limit(limit).offset(offset).all()
        return [db._dict(r) for r in rows], total


def retry(job_id: str) -> bool:
    """Relance manuellement un travail en échec, depuis le back-office.

    Le compteur de tentatives repart à zéro : une relance manuelle intervient après
    correction de la cause (clé de modèle renouvelée, quota rechargé), et conserver
    l'ancien compteur ferait échouer immédiatement un travail qui aurait toutes ses
    chances d'aboutir.
    """
    now = _utcnow()
    with db.session_scope() as s:
        row = s.get(db.Job, job_id)
        if row is None or row.status not in {STATUS_FAILED, STATUS_DONE}:
            return False
        row.status = STATUS_QUEUED
        row.attempts = 0
        row.run_at = now
        row.locked_at = None
        row.locked_by = None
        row.finished_at = None
        row.error = None
        row.updated_at = now
        return True


def purge_old(days: int | None = None) -> int:
    """Supprime les travaux terminés au-delà de la rétention. Retourne le nombre effacé.

    Les échecs sont conservés plus longtemps que les succès : un travail réussi n'a
    plus rien à raconter, un travail en échec sert au diagnostic.
    """
    keep = days or settings.job_retention_days
    with db.session_scope() as s:
        deleted = (
            s.query(db.Job)
            .filter(db.Job.status == STATUS_DONE, db.Job.finished_at < _utcnow() - timedelta(days=keep))
            .delete(synchronize_session=False)
        )
        deleted += (
            s.query(db.Job)
            .filter(db.Job.status == STATUS_FAILED, db.Job.finished_at < _utcnow() - timedelta(days=keep * 3))
            .delete(synchronize_session=False)
        )
        return int(deleted)
