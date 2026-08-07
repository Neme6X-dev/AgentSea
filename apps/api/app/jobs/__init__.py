"""File de travaux durable et son exécutant.

Point d'entrée unique pour les routeurs : `submit()`. Il masque la seule décision
que les appelants n'ont pas à connaître — file réelle ou exécution immédiate.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.jobs import queue
from app.jobs.handlers import HANDLERS, on_permanent_failure

logger = logging.getLogger("app.jobs")

# Références aux exécutions immédiates. Sans elles, l'ordonnanceur asyncio peut
# collecter une tâche encore vivante et le travail s'arrêterait en silence.
_inline_tasks: set[asyncio.Task] = set()


def submit(
    kind: str,
    payload: dict[str, Any],
    *,
    user_id: int | None = None,
    session_id: str | None = None,
    priority: int = 3,
) -> str:
    """Confie un travail à la file, ou l'exécute sur-le-champ en mode `inline`.

    Le mode se règle par `JOB_MODE`. En développement, `inline` évite d'avoir à lancer
    un second processus pour voir un site se générer. En production, `queue` est le
    seul mode acceptable : voir l'en-tête de `app.jobs.queue` pour le détail.

    Returns:
        L'identifiant du travail — celui de la file, ou un identifiant local en mode
        `inline`, afin que l'appelant ait toujours quelque chose à consigner.
    """
    job_id = queue.enqueue(
        kind, payload, user_id=user_id, session_id=session_id, priority=priority
    )

    if settings.job_mode == "inline":
        task = asyncio.create_task(_run_inline(job_id, kind, payload))
        _inline_tasks.add(task)
        task.add_done_callback(_inline_tasks.discard)

    return job_id


async def _run_inline(job_id: str, kind: str, payload: dict[str, Any]) -> None:
    """Exécute un travail dans le processus web (développement uniquement).

    Reprend délibérément le même cycle de vie que le worker — réservation, succès ou
    échec consigné, session mise en erreur si tout est épuisé — pour que le
    comportement observé en développement soit celui de la production.
    """
    job = queue.claim("inline", kinds=(kind,))
    if job is None or job["id"] != job_id:
        # Un worker a été plus rapide : c'est le comportement attendu si les deux
        # modes cohabitent, et il n'y a rien à faire de plus.
        return

    handler = HANDLERS.get(kind)
    if handler is None:
        queue.fail(job_id, f"Type de travail inconnu : {kind}")
        return

    try:
        await handler(payload)
    except Exception as exc:
        logger.exception("Travail %s (%s) en échec en mode inline", job_id, kind)
        if not queue.fail(job_id, f"{type(exc).__name__}: {exc}"):
            on_permanent_failure({**job, "attempts": job["attempts"]}, str(exc))
        return

    queue.complete(job_id)
