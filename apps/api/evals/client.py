"""Client HTTP du backend, pour les harnais d'évaluation.

Tape la vraie API (serveur lancé via `./run.sh`), pas les fonctions internes : c'est le
seul moyen de mesurer ce que n8n et le front obtiennent réellement, gestion d'auth et
sérialisation des contrats comprises.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.contracts import DesignSpec, GeneratedSite  # noqa: E402

BASE_URL = os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EVAL_PASSWORD = "EvalHarness-2026!"
TIMEOUT = float(os.environ.get("EVAL_TIMEOUT_S", "300"))


class EvalClient:
    """Session authentifiée + accès aux fichiers produits sur disque."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=TIMEOUT)
        self._token: str | None = None

    # ----------------------------------------------------------------- auth --
    def login(self, email: str | None = None) -> str:
        """Crée (ou réutilise) un compte d'éval et mémorise son JWT."""
        email = email or f"eval-{uuid.uuid4().hex[:8]}@harness.local"
        r = self._client.post(
            "/api/auth/register",
            json={"email": email, "password": EVAL_PASSWORD, "name": "Harnais d'éval"},
        )
        if r.status_code == 409:
            r = self._client.post("/api/auth/login", json={"email": email, "password": EVAL_PASSWORD})
        r.raise_for_status()
        self._token = r.json()["access_token"]
        return self._token

    @property
    def _auth(self) -> dict[str, str]:
        if self._token is None:
            raise RuntimeError("Appelez login() d'abord.")
        return {"Authorization": f"Bearer {self._token}"}

    @property
    def service_auth(self) -> dict[str, str]:
        """En-tête d'appel service, tel que n8n l'utilise (INTERNAL_API_KEY en bearer)."""
        return {"Authorization": f"Bearer {settings.internal_api_key}"}

    # -------------------------------------------------------------- requêtes --
    def _post(self, path: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None) -> httpx.Response:
        return self._client.post(path, json=payload, headers=headers or self._auth)

    def create_session(self, prompt: str) -> dict[str, Any]:
        r = self._post("/api/sessions", {"prompt": prompt})
        r.raise_for_status()
        return r.json()

    def agent_code(self, session_id: str, spec: dict[str, Any], instruction: str | None = None) -> tuple[dict[str, Any], float]:
        payload: dict[str, Any] = {"session_id": session_id, "design_spec": spec}
        if instruction:
            payload["instruction"] = instruction
        started = time.monotonic()
        r = self._post("/api/agents/code", payload)
        elapsed = time.monotonic() - started
        r.raise_for_status()
        return r.json(), elapsed

    def agent_review(self, session_id: str, slug: str) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        r = self._post("/api/agents/review", {"session_id": session_id, "slug": slug})
        elapsed = time.monotonic() - started
        r.raise_for_status()
        return r.json(), elapsed

    def deploy(self, session_id: str, slug: str) -> dict[str, Any]:
        r = self._post("/api/deploy", {"session_id": session_id, "slug": slug})
        r.raise_for_status()
        return r.json()

    def edit(self, session_id: str, instruction: str, **extra: Any) -> tuple[httpx.Response, float]:
        """Retourne la réponse brute : le harnais teste aussi les cas d'erreur (409…)."""
        started = time.monotonic()
        r = self._post(f"/api/sessions/{session_id}/edit", {"instruction": instruction, **extra})
        return r, time.monotonic() - started

    def publish(self, session_id: str, **payload: Any) -> httpx.Response:
        """Endpoint de publication explicite (Lot 1). 404 tant qu'il n'existe pas."""
        return self._post(f"/api/sessions/{session_id}/publish", payload)

    def get_session(self, session_id: str) -> dict[str, Any]:
        r = self._client.get(f"/api/sessions/{session_id}", headers=self._auth)
        r.raise_for_status()
        return r.json()

    def fetch_live(self, slug: str) -> str | None:
        """Contenu servi en live, ou None si rien n'est publié."""
        r = self._client.get(f"/sites/{slug}/live/index.html")
        return r.text if r.status_code == 200 else None

    # --------------------------------------------------------------- disque --
    @staticmethod
    def load_version(slug: str, version: int) -> GeneratedSite:
        d = settings.sites_dir / slug / f"v{version}"
        return GeneratedSite(
            html=(d / "index.html").read_text(encoding="utf-8"),
            css=(d / "style.css").read_text(encoding="utf-8"),
            js=(d / "script.js").read_text(encoding="utf-8"),
        )

    @staticmethod
    def spec_model(spec: dict[str, Any]) -> DesignSpec:
        return DesignSpec.model_validate(spec)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EvalClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def check_server(base_url: str = BASE_URL) -> None:
    """Échoue tôt et clairement si le backend n'écoute pas."""
    try:
        httpx.get(base_url + "/", timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Backend injoignable sur {base_url} ({exc}).\nLancez-le avec ./run.sh, "
            "ou pointez EVAL_BASE_URL vers la bonne instance."
        ) from exc
