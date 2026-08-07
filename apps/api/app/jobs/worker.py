"""Exécutant de la file de travaux.

Se lance à côté de l'API :

    python -m app.jobs.worker                 # un exécutant, concurrence par défaut
    JOB_CONCURRENCY=4 python -m app.jobs.worker

Plusieurs instances peuvent tourner sur des machines différentes : la réservation par
`SKIP LOCKED` garantit qu'un travail n'est jamais pris deux fois. Monter en charge se
fait donc en lançant des workers, sans rien reconfigurer.

L'arrêt est **gracieux** : sur `SIGTERM` — ce qu'envoie Docker au redéploiement — le
worker cesse de piocher mais laisse les générations en cours se terminer. Les couper
net gaspillerait des appels au modèle déjà facturés et laisserait des sessions à mi-
chemin.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid

from app import db
from app.config import settings
from app.core import logging as applog
from app.jobs import queue
from app.jobs.handlers import HANDLERS, on_permanent_failure

logger = logging.getLogger("app.jobs.worker")

#: Toutes les N boucles à vide, on effectue l'entretien : reprise des travaux
#: orphelins et purge des anciens. Adossé au nombre de tours plutôt qu'à une horloge :
#: un worker occupé n'a pas besoin de faire le ménage, il a mieux à faire.
_MAINTENANCE_EVERY = 30


class Worker:
    """Boucle de travail, avec concurrence bornée et arrêt gracieux."""

    def __init__(self, concurrency: int | None = None) -> None:
        self.id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:4]}"
        self.concurrency = concurrency or settings.job_concurrency
        self.stopping = False
        self._running: set[asyncio.Task] = set()
        self._idle_loops = 0

    async def run(self) -> None:
        logger.info(
            "Worker %s démarré (concurrence %s, sondage %.1f s)",
            self.id, self.concurrency, settings.job_poll_interval_s,
        )
        # Un worker qui démarre est souvent celui qui remplace un worker tué : c'est
        # le meilleur moment pour reprendre ce que le précédent a laissé en plan.
        queue.reclaim_stale()

        while not self.stopping:
            if len(self._running) >= self.concurrency:
                await asyncio.sleep(0.1)
                continue

            job = queue.claim(self.id)
            if job is None:
                self._idle_loops += 1
                if self._idle_loops % _MAINTENANCE_EVERY == 0:
                    self._maintenance()
                await asyncio.sleep(settings.job_poll_interval_s)
                continue

            self._idle_loops = 0
            task = asyncio.create_task(self._execute(job))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

        if self._running:
            logger.info("Arrêt demandé — attente de %s travail(x) en cours", len(self._running))
            await asyncio.gather(*self._running, return_exceptions=True)
        logger.info("Worker %s arrêté", self.id)

    async def _execute(self, job: dict) -> None:
        """Exécute un travail, en isolant complètement son échec du reste du worker."""
        job_id, kind = job["id"], job["kind"]
        # L'identifiant de corrélation du worker reprend celui du travail : les lignes
        # de journal du processus web et celles du worker se recoupent alors sur une
        # même clé, ce qui est tout l'intérêt de la chaîne de traçage.
        applog.bind(request_id=job_id, user_id=job.get("user_id"))

        handler = HANDLERS.get(kind)
        if handler is None:
            # Type inconnu : forcément une version de code plus récente que la nôtre.
            # On échoue proprement plutôt que d'improviser ; un worker à jour le
            # reprendra.
            queue.fail(job_id, f"Type de travail non pris en charge par ce worker : {kind}")
            return

        started = time.perf_counter()
        logger.info(
            "▶ %s (%s) tentative %s/%s", job_id, kind, job["attempts"], job["max_attempts"],
            extra={"job_id": job_id, "kind": kind, "session_id": job.get("session_id")},
        )
        try:
            await handler(job["payload"])
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "✖ %s (%s) après %s ms", job_id, kind, elapsed,
                extra={"job_id": job_id, "kind": kind, "session_id": job.get("session_id")},
            )
            will_retry = queue.fail(job_id, f"{type(exc).__name__}: {exc}")
            if not will_retry:
                # `on_permanent_failure` écrit sur la session : si cette écriture
                # échoue à son tour (base injoignable), la faire remonter tuerait le
                # worker alors que le travail est déjà correctement marqué en échec.
                with contextlib.suppress(Exception):
                    on_permanent_failure({**job, "attempts": job["attempts"]}, str(exc))
            return

        elapsed = int((time.perf_counter() - started) * 1000)
        queue.complete(job_id, duration_ms=elapsed)
        logger.info(
            "✔ %s (%s) en %s ms", job_id, kind, elapsed,
            extra={"job_id": job_id, "kind": kind, "duration_ms": elapsed},
        )

    def _maintenance(self) -> None:
        """Entretien périodique, exécuté uniquement quand la file est vide."""
        try:
            reclaimed = queue.reclaim_stale()
            purged = queue.purge_old()
            if reclaimed or purged:
                logger.info("Entretien : %s repris, %s purgés", reclaimed, purged)
        except Exception:
            # L'entretien est du confort : son échec ne doit jamais arrêter le worker,
            # qui a pour mission première de servir la file.
            logger.exception("Entretien de la file en échec")

    def request_stop(self) -> None:
        if not self.stopping:
            logger.info("Signal d'arrêt reçu — plus aucun nouveau travail ne sera pris")
        self.stopping = True


async def main() -> None:
    applog.configure(settings.log_level, settings.log_json)
    db.configure_engine()

    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)

    await worker.run()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
