"""Journalisation structurée et identifiant de corrélation.

Le besoin est concret : une génération de site traverse le routeur, la file de
travaux, un worker séparé, deux agents et le fournisseur de modèle. Quand un client
signale « mon site n'est jamais sorti », il faut pouvoir remonter *sa* requête à
travers ces cinq composants. Un identifiant propagé dans un `ContextVar` et repris
automatiquement par chaque ligne de journal rend cette recherche immédiate ; sans lui,
il faut recouper des horodatages à la main.

Le format JSON n'est activé qu'en production (`LOG_JSON`) : un agrégateur le lit
nativement, alors qu'en développement le texte reste plus confortable dans un terminal.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

#: Identifiant de la requête (ou du travail) en cours. Vide hors contexte.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)

# Champs internes de `LogRecord` : tout le reste est un attribut ajouté par
# l'appelant via `extra=`, et mérite de figurer dans la sortie structurée.
_RESERVED = frozenset(
    """name msg args levelname levelno pathname filename module exc_info exc_text
    stack_info lineno funcName created msecs relativeCreated thread threadName
    processName process taskName message asctime""".split()
)


def new_request_id() -> str:
    """Identifiant court, lisible à l'œil dans un terminal comme dans une URL."""
    return uuid.uuid4().hex[:12]


class ContextFilter(logging.Filter):
    """Injecte l'identifiant de corrélation dans chaque enregistrement."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        record.user_id = user_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Une ligne JSON par événement, sans dépendance externe."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if getattr(record, "user_id", None) is not None:
            payload["user_id"] = record.user_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload or key.startswith("_"):
                continue
            # Un `extra` non sérialisable ne doit pas faire disparaître la ligne :
            # une trace dégradée vaut mieux qu'une trace absente au moment où on la
            # cherche.
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Format lisible en développement, identifiant de requête compris."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )


def configure(level: str = "INFO", json_output: bool = False) -> None:
    """Installe la configuration de journalisation du processus.

    Idempotent : appelée au démarrage de l'API comme du worker, y compris quand les
    deux tournent dans le même processus en développement.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())
    handler.addFilter(ContextFilter())
    root.addHandler(handler)

    # Uvicorn installe ses propres handlers : on les neutralise pour que tout passe
    # par le nôtre, sinon chaque requête apparaît deux fois, dans deux formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True

    # Ces bibliothèques journalisent chaque requête HTTP sortante en INFO : sur une
    # génération qui en émet des dizaines, le signal utile disparaît sous le bruit.
    for noisy in ("httpx", "httpcore", "paramiko", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def bind(request_id: str = "", user_id: int | None = None) -> None:
    """Attache un contexte de corrélation au fil d'exécution courant.

    Utilisé par le middleware HTTP et par le worker, qui reprend l'identifiant stocké
    sur le travail — c'est ce qui permet de suivre une génération depuis le clic de
    l'utilisateur jusqu'à l'écriture des fichiers, à travers deux processus.
    """
    request_id_var.set(request_id or new_request_id())
    user_id_var.set(user_id)


def current_request_id() -> str:
    return request_id_var.get() or ""
