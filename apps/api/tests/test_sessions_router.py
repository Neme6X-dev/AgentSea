"""Tests du router /api/sessions (création, list, détail, artifacts, edit, retry)."""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.contracts import DesignSpec, EditSessionRequest
from app.jobs.handlers import handle_edit
from app.main import app
from app.security import current_user

client = TestClient(app, raise_server_exceptions=False)
BASE = "/api/sessions"
# `plan` et `country` font partie du compte depuis l'ouverture des offres : les quotas
# et la tarification régionale s'y réfèrent à chaque appel.
USER = {
    "id": 1, "email": "a@example.com", "name": "A", "provider": "local",
    "role": "user", "plan": "pro", "country": "BJ", "status": "active",
}


async def _run_edit(session_id: str, slug: str, payload: EditSessionRequest, current_spec) -> None:
    """Passerelle vers le handler de la file, à la signature d'origine.

    Le pipeline a déménagé dans `app.jobs.handlers` ; les tests qui l'éprouvent
    gardent leur formulation, qui décrit une intention métier et non un emplacement
    de code. Le spec courant est fourni par le patch de `get_latest_design_spec`.
    """
    with patch("app.jobs.handlers.get_latest_design_spec", return_value=current_spec):
        await handle_edit({"session_id": session_id, "slug": slug, "request": payload.model_dump()})


@pytest.fixture
def authed():
    app.dependency_overrides[current_user] = lambda: USER
    yield
    app.dependency_overrides.pop(current_user, None)


def _session_dict(**over) -> dict:
    base = {
        "id": "abc123",
        "slug": "chez-amara",
        "prompt": "restaurant africain",
        "status": "pending",
        "current_step": None,
        "steps": [],
        "site_url": None,
        "error": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "user_id": 1,
    }
    base.update(over)
    return base

class TestCreate:
    def test_create_session(self, authed):
        with patch("app.routers.sessions.db.allocate_slug", return_value="chez-amara"), patch(
            "app.routers.sessions.db.create_session", return_value="abc123"
        ):
            r = client.post(BASE, json={"prompt": "restaurant africain"})
        assert r.status_code == 201
        assert r.json() == {"id": "abc123", "slug": "chez-amara", "status": "pending"}

    def test_create_invalid_payload(self, authed):
        r = client.post(BASE, json={"prompt": ""})
        assert r.status_code == 422


class TestList:
    def test_list(self, authed):
        with patch("app.routers.sessions.db.list_sessions", return_value=[_session_dict()]), patch(
            "app.routers.sessions.db.get_artifacts", return_value=[]
        ):
            r = client.get(BASE)
        assert r.status_code == 200
        assert r.json()[0]["slug"] == "chez-amara"


class TestDetail:
    def test_get_ok(self, authed):
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict()), patch(
            "app.routers.sessions.db.get_artifacts", return_value=[]
        ):
            r = client.get(f"{BASE}/abc123")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_get_404(self, authed):
        with patch("app.routers.sessions.db.get_session", return_value=None):
            r = client.get(f"{BASE}/nope")
        assert r.status_code == 404

    def test_get_forbidden(self, authed):
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict(user_id=999)):
            r = client.get(f"{BASE}/abc123")
        assert r.status_code == 403


class TestArtifacts:
    def test_list_artifacts(self, authed):
        art = {"id": 1, "session_id": "abc123", "kind": "site", "version": 1, "payload": {}, "created_at": "2026"}
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict()), patch(
            "app.routers.sessions.db.get_artifacts", return_value=[art]
        ):
            r = client.get(f"{BASE}/abc123/artifacts")
        assert r.status_code == 200
        assert r.json()[0]["kind"] == "site"


class TestEdit:
    def test_edit_no_spec(self, authed):
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict()), patch(
            "app.routers.sessions.get_latest_design_spec", return_value=None
        ):
            r = client.post(f"{BASE}/abc123/edit", json={"instruction": "change les couleurs"})
        assert r.status_code == 400

    def test_edit_is_accepted_and_scheduled(self, authed):
        """202 : la modification part en tâche de fond, comme la génération."""
        spec = {"name": "Chez Amara", "tagline": "r", "language": "fr", "sections": []}
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict()), patch(
            "app.routers.sessions.get_latest_design_spec", return_value=spec
        ), patch("app.routers.sessions.db.get_artifacts", return_value=[]), patch("app.routers.sessions.jobs.submit") as spawn:
            r = client.post(f"{BASE}/abc123/edit", json={"instruction": "change les couleurs"})
        assert r.status_code == 202
        spawn.assert_called_once()


def _artifacts(*, sites: list[int] = (), deploys: list[int] = (), reports: dict[int, dict] | None = None):
    """Simule db.get_artifacts, filtré par `kind` comme le fait la vraie fonction."""
    reports = reports or {}

    def _get(session_id: str, kind: str | None = None):
        if kind == "site":
            return [{"kind": "site", "version": v, "payload": {}, "created_at": "2026"} for v in sites]
        if kind == "deploy":
            return [
                {"kind": "deploy", "version": v, "payload": {"version": v, "url": "u", "target": "local"},
                 "created_at": "2026"}
                for v in deploys
            ]
        if kind == "report":
            return [
                {"kind": "report", "version": v, "payload": p, "created_at": "2026"}
                for v, p in sorted(reports.items())
            ]
        return []

    return _get


def _latest_deploy(deploys: list[int]):
    """Simule db.latest_artifact('deploy') : le dernier écrit, pas le plus haut numéro."""

    def _get(session_id: str, kind: str):
        if kind == "deploy" and deploys:
            version = deploys[-1]
            return {"kind": "deploy", "version": version, "payload": {"version": version},
                    "created_at": "2026"}
        return None

    return _get


def _report(verdict: str, score: int, findings: list[dict] | None = None) -> dict:
    return {
        "score": score,
        "verdict": verdict,
        "dimensions": {"security": score, "design_fidelity": score, "accessibility": score,
                       "responsiveness": score, "content": score},
        "findings": findings or [],
        "summary": "test",
    }


class TestEditPreservesPublishedSite:
    """Une retouche ne publie jamais d'elle-même — même sur un site jamais mis en ligne :
    la mise en ligne reste un geste explicite via `/publish`."""

    SPEC = DesignSpec.model_validate({"name": "Chez Amara", "tagline": "r", "language": "fr", "sections": []})

    @pytest.mark.asyncio
    async def test_edit_never_auto_publishes_even_on_a_never_published_site(self, authed):
        """Rien n'est en ligne : la nouvelle version reste quand même en preview."""
        payload = EditSessionRequest(instruction="ajoute une section")
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=1), patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ), patch("app.jobs.handlers.run_deploy_step", new_callable=AsyncMock) as deploy, patch(
            "app.jobs.handlers.db.set_session_field"
        ) as set_field, patch("app.jobs.handlers.db.add_artifact"), patch(
            "app.jobs.handlers.db.latest_version", return_value=0
        ), patch("app.jobs.handlers.db.get_session", return_value=None):
            await _run_edit("abc123", "chez-amara", payload, self.SPEC)

        assert deploy.await_count == 0
        assert set_field.call_args.kwargs["status"] == "ready"

    @pytest.mark.asyncio
    async def test_edit_of_published_site_stays_in_preview(self, authed):
        """Un site publié : l'édition s'arrête en preview et le live n'est pas touché."""
        payload = EditSessionRequest(instruction="change le texte")
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=2), patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ), patch("app.jobs.handlers.run_deploy_step", new_callable=AsyncMock) as deploy, patch(
            "app.jobs.handlers.db.update_step"
        ) as step, patch("app.jobs.handlers.db.set_session_field") as set_field, patch(
            "app.jobs.handlers.db.add_artifact"
        ), patch("app.jobs.handlers.db.latest_version", return_value=1), patch(
            "app.jobs.handlers.db.get_session", return_value=None
        ):
            await _run_edit("abc123", "chez-amara", payload, self.SPEC)

        assert deploy.await_count == 0, "l'édition a republié sans confirmation"
        assert any(call.args[1] == "preview" for call in step.call_args_list)
        # Statut terminal, sinon le front interrogerait sans fin une session déjà finie.
        assert set_field.call_args.kwargs["status"] == "ready"

    def test_published_site_keeps_its_live_version_in_the_view(self, authed):
        """La vue distingue la version en ligne des versions seulement prévisualisables."""
        arts = _artifacts(sites=[1, 2], deploys=[1])
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict(status="deployed")), patch(
            "app.routers.sessions.get_latest_design_spec", return_value=self.SPEC
        ), patch("app.routers.sessions.jobs.submit"), patch(
            "app.services.db.get_artifacts", side_effect=arts
        ), patch("app.services.db.latest_artifact", side_effect=_latest_deploy([1])), patch(
            "app.routers.sessions.db.get_artifacts", side_effect=arts
        ):
            r = client.post(f"{BASE}/abc123/edit", json={"instruction": "change le texte"})

        body = r.json()
        assert body["published_version"] == 1
        assert [p["version"] for p in body["previews"]] == [1, 2]
        assert [p["published"] for p in body["previews"]] == [True, False]


class TestRedesign:
    """Refonte complète : nouveau spec, et surtout site actuel NON transmis au codeur."""

    SPEC = DesignSpec.model_validate({"name": "Chez Amara", "tagline": "r", "language": "fr", "sections": []})
    NOUVEAU = {
        "name": "Chez Amara",
        "tagline": "Éditorial sombre",
        "language": "fr",
        "sections": [],
        "palette": {"primary": "#c9a227", "secondary": "#1a1a1a", "accent": "#e0623d",
                    "bg": "#121212", "text": "#f2efe9"},
    }

    def _patches(self, code_mock):
        return (
            patch("app.jobs.handlers.run_code_step", new=code_mock),
            patch("app.jobs.handlers.run_review_step", new_callable=AsyncMock),
            patch("app.jobs.handlers.db.set_session_field"),
            patch("app.jobs.handlers.db.add_artifact"),
            patch("app.jobs.handlers.db.latest_version", return_value=1),
            patch("app.jobs.handlers.db.get_session", return_value=None),
        )

    async def _edit(self, code_mock, payload, extra=()):
        with ExitStack() as stack:
            for p in (*self._patches(code_mock), *extra):
                stack.enter_context(p)
            await _run_edit("abc123", "chez-amara", payload, self.SPEC)

    @pytest.mark.asyncio
    async def test_tweak_keeps_the_current_spec_and_site(self, authed):
        code = AsyncMock(return_value=2)
        await self._edit(code, EditSessionRequest(instruction="change le texte"))
        assert code.await_args.kwargs["redesign"] is False
        assert code.await_args.args[2] == self.SPEC

    @pytest.mark.asyncio
    async def test_supplied_design_spec_triggers_a_redesign(self, authed):
        """Un spec fourni par n8n vaut refonte, quel que soit le mode annoncé."""
        code = AsyncMock(return_value=2)
        payload = EditSessionRequest(instruction="passe en sombre", design_spec=self.NOUVEAU)
        await self._edit(code, payload)
        assert code.await_args.kwargs["redesign"] is True
        # Le spec effectif est le nouveau : valider contre l'ancien rejetterait la refonte
        # pour infidélité à une palette qu'on vient de remplacer.
        assert code.await_args.args[2].palette.bg == "#121212"

    @pytest.mark.asyncio
    async def test_redesign_without_spec_regenerates_one(self, authed):
        code = AsyncMock(return_value=2)
        regenerated = DesignSpec.model_validate(self.NOUVEAU)
        designer_patch = patch(
            "app.jobs.handlers.designer.build_design_spec",
            new_callable=AsyncMock,
            return_value=(regenerated, "interne"),
        )
        with ExitStack() as stack:
            for p in self._patches(code):
                stack.enter_context(p)
            designer = stack.enter_context(designer_patch)
            await _run_edit(
                "abc123",
                "chez-amara",
                EditSessionRequest(instruction="je veux un style totalement différent", mode="redesign"),
                self.SPEC,
            )

        assert code.await_args.kwargs["redesign"] is True
        # L'ancien spec est passé en contexte pour préserver nom et contacts.
        assert designer.await_args.kwargs["previous"] == self.SPEC


class TestPublish:
    def test_publishes_latest_by_default(self, authed):
        arts = _artifacts(sites=[1, 2], deploys=[1], reports={2: _report("pass", 90)})
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict(status="deployed")), patch(
            "app.routers.sessions.db.latest_version", return_value=2
        ), patch("app.routers.sessions.run_deploy_step", new_callable=AsyncMock) as deploy, patch(
            "app.services.db.get_artifacts", side_effect=arts
        ), patch("app.routers.sessions.db.get_artifacts", side_effect=arts):
            r = client.post(f"{BASE}/abc123/publish", json={})
        assert r.status_code == 200
        assert deploy.await_args.args[2] == 2

    def test_rollback_to_earlier_version(self, authed):
        """Republier une version antérieure : c'est le retour arrière offert au front."""
        arts = _artifacts(sites=[1, 2, 3], deploys=[3], reports={1: _report("pass", 92)})
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict(status="deployed")), patch(
            "app.routers.sessions.run_deploy_step", new_callable=AsyncMock
        ) as deploy, patch("app.services.db.get_artifacts", side_effect=arts), patch(
            "app.routers.sessions.db.get_artifacts", side_effect=arts
        ):
            r = client.post(f"{BASE}/abc123/publish", json={"version": 1})
        assert r.status_code == 200
        assert deploy.await_args.args[2] == 1

    def test_unknown_version_is_404(self, authed):
        arts = _artifacts(sites=[1], deploys=[])
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict()), patch(
            "app.services.db.get_artifacts", side_effect=arts
        ), patch("app.routers.sessions.db.get_artifacts", side_effect=arts):
            r = client.post(f"{BASE}/abc123/publish", json={"version": 7})
        assert r.status_code == 404

    def test_failing_version_is_blocked(self, authed):
        """Verdict `fail` : on refuse, en disant précisément ce qui bloque."""
        findings = [{"severity": "critical", "category": "security", "title": "eval() détecté",
                     "detail": "", "fix": "", "file": "script.js"}]
        arts = _artifacts(sites=[1, 2], deploys=[1], reports={2: _report("fail", 30, findings)})
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict(status="deployed")), patch(
            "app.routers.sessions.db.latest_version", return_value=2
        ), patch("app.routers.sessions.run_deploy_step", new_callable=AsyncMock) as deploy, patch(
            "app.services.db.get_artifacts", side_effect=arts
        ), patch("app.routers.sessions.db.get_artifacts", side_effect=arts):
            r = client.post(f"{BASE}/abc123/publish", json={})
        assert r.status_code == 409
        assert deploy.await_count == 0
        assert "eval() détecté" in r.json()["detail"]["blocking_findings"]

    def test_force_publishes_despite_failure(self, authed):
        """Le garde-fou protège, il n'interdit pas : l'utilisateur reste décisionnaire."""
        arts = _artifacts(sites=[1, 2], deploys=[1], reports={2: _report("fail", 30)})
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict(status="deployed")), patch(
            "app.routers.sessions.db.latest_version", return_value=2
        ), patch("app.routers.sessions.run_deploy_step", new_callable=AsyncMock) as deploy, patch(
            "app.services.db.get_artifacts", side_effect=arts
        ), patch("app.routers.sessions.db.get_artifacts", side_effect=arts):
            r = client.post(f"{BASE}/abc123/publish", json={"force": True})
        assert r.status_code == 200
        assert deploy.await_count == 1


class TestRetry:
    def test_retry_no_failure(self, authed):
        with patch("app.routers.sessions.db.get_session", return_value=_session_dict()):
            r = client.post(f"{BASE}/abc123/retry")
        assert r.status_code == 400

    def test_retry_deploy(self, authed):
        s = _session_dict(
            steps=[
                {"step": "code", "status": "done", "detail": "", "ts": "2026"},
                {"step": "deploy", "status": "failed", "detail": "", "ts": "2026"},
            ],
        )
        with patch("app.routers.sessions.db.get_session", return_value=s), patch(
            "app.routers.sessions.db.latest_version", return_value=1
        ), patch("app.routers.sessions.run_deploy_step", new_callable=AsyncMock), patch(
            "app.routers.sessions.db.get_artifacts", return_value=[]
        ):
            r = client.post(f"{BASE}/abc123/retry")
        assert r.status_code == 200