"""Génération asynchrone : la main est rendue tout de suite, le travail part en file.

Ce contrat est ce qui permet au front d'afficher le travail réel des agents : un appel
synchrone ne rendrait la main qu'à la fin, et il n'y aurait rien à montrer pendant la
minute de génération.

L'endpoint et le pipeline sont éprouvés séparément — l'un ordonnance, l'autre exécute.
Les faire passer par la boucle du client de test obligerait à démarrer le `lifespan`,
donc à rejouer les migrations Alembic à chaque test.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import db
from app.contracts import DesignSpec
from app.jobs.handlers import handle_generate, on_permanent_failure
from app.main import app
from app.security import current_user

client = TestClient(app)
BASE = "/api/dev/generate"
SPEC = DesignSpec(name="Chez Amara")


@pytest.fixture(autouse=True)
def authed():
    user = db.create_user("a@b.c", password_hash="hash", name="A")
    app.dependency_overrides[current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


@pytest.fixture
def session(authed):
    """Session ouverte, telle que l'endpoint la crée avant de rendre la main."""
    slug = db.allocate_slug("Chez Amara")
    return db.create_session(authed["id"], "un restaurant", slug), slug


def _payload(session_id: str, slug: str, spec: DesignSpec | None) -> dict:
    return {
        "session_id": session_id,
        "slug": slug,
        "prompt": "un restaurant",
        "design_spec": spec.model_dump() if spec else None,
    }


def _steps(session_id):
    return db.get_session(session_id)["steps"] or []


class TestEndpoint:
    def test_returns_202_without_waiting_for_the_pipeline(self):
        with patch("app.routers.dev.jobs.submit") as submit:
            r = client.post(BASE, json={"prompt": "un restaurant", "design_spec": SPEC.model_dump()})

        assert r.status_code == 202
        # La génération est bien confiée à la file, pas attendue.
        submit.assert_called_once()

    def test_session_is_queryable_right_away(self):
        """Le front doit pouvoir interroger la session dès la réponse."""
        with patch("app.routers.dev.jobs.submit"):
            r = client.post(BASE, json={"prompt": "un restaurant", "design_spec": SPEC.model_dump()})

        body = r.json()
        assert db.get_session(body["id"]) is not None
        # `running`, pas `pending` : la première étape est déjà inscrite, et le front
        # doit continuer d'interroger la session — seuls les statuts terminaux l'arrêtent.
        assert body["status"] == "running"

    def test_slug_follows_the_spec_name(self):
        """Le nom retenu au cadrage est plus fidèle que la première phrase du client."""
        with patch("app.routers.dev.jobs.submit"):
            r = client.post(
                BASE,
                json={"prompt": "je sais pas trop ce que je veux", "design_spec": SPEC.model_dump()},
            )
        assert r.json()["slug"].startswith("chez-amara")

    def test_country_defaults_to_the_account(self, authed):
        """Un commerçant génère presque toujours pour son propre marché."""
        db.update_user(authed["id"], country="CI")
        app.dependency_overrides[current_user] = lambda: db.get_user(authed["id"])
        with patch("app.routers.dev.jobs.submit"):
            r = client.post(BASE, json={"prompt": "une boutique"})
        assert db.get_session(r.json()["id"])["country"] == "CI"

    def test_generation_consumes_the_monthly_quota(self, authed):
        """Le compteur doit bouger : c'est lui qui applique la limite du forfait."""
        from app.billing import quotas

        with patch("app.routers.dev.jobs.submit"):
            client.post(BASE, json={"prompt": "un restaurant"})
        assert db.get_usage(authed["id"], "generations", quotas.current_period()) == 1

    def test_quota_exhaustion_is_402_and_creates_no_session(self, authed):
        """Dépasser son forfait ne doit pas laisser de session vide dans les projets."""
        from app.billing import plans, quotas

        limit = plans.get("decouverte").quotas.generations_per_month
        db.increment_usage(authed["id"], "generations", quotas.current_period(), limit)

        before = db.count_sessions(authed["id"])
        with patch("app.routers.dev.jobs.submit") as submit:
            r = client.post(BASE, json={"prompt": "un restaurant"})

        assert r.status_code == 402
        assert submit.call_count == 0
        assert db.count_sessions(authed["id"]) == before

    def test_requires_authentication(self):
        app.dependency_overrides.clear()
        r = client.post(BASE, json={"prompt": "un restaurant"})
        assert r.status_code == 401


class TestPipeline:
    @pytest.mark.asyncio
    async def test_runs_code_then_review_and_stops_at_ready(self, session):
        """La génération ne publie jamais d'elle-même : elle s'arrête à `ready`, en
        attente d'un clic explicite sur « Publier » — cf. `mark_ready`."""
        session_id, slug = session
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=1) as code, patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ) as review:
            await handle_generate(_payload(session_id, slug, SPEC))

        code.assert_awaited_once()
        review.assert_awaited_once()
        # La revue porte sur la version que le codeur vient d'écrire.
        assert review.await_args.args[2] == 1

        row = db.get_session(session_id)
        assert row["status"] == "ready"
        assert row.get("site_url") is None

    @pytest.mark.asyncio
    async def test_conversation_spec_short_circuits_the_designer(self, session):
        """Le cadrage fait foi : relancer un designer produirait un autre site."""
        session_id, slug = session
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=1), patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ), patch(
            "app.jobs.handlers.designer.build_design_spec", new_callable=AsyncMock
        ) as designer:
            await handle_generate(_payload(session_id, slug, SPEC))

        designer.assert_not_awaited()
        assert any("cadrage" in (s.get("detail") or "") for s in _steps(session_id))

    @pytest.mark.asyncio
    async def test_designer_runs_when_no_spec_was_provided(self, session):
        session_id, slug = session
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=1), patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ), patch(
            "app.jobs.handlers.designer.build_design_spec",
            new_callable=AsyncMock,
            return_value=(DesignSpec(name="Déduit"), "interne"),
        ) as designer:
            await handle_generate(_payload(session_id, slug, None))

        designer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_design_step_is_recorded_for_the_scene(self, session):
        """La scène 3D lit ces étapes : sans elles, les agents n'ont rien à refléter."""
        session_id, slug = session
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=1), patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ):
            await handle_generate(_payload(session_id, slug, SPEC))

        design = [s for s in _steps(session_id) if s["step"] == "design"]
        assert [s["status"] for s in design] == ["running", "done"]

    @pytest.mark.asyncio
    async def test_country_and_sector_are_recorded_on_the_session(self, session):
        """Ces deux champs alimentent la ventilation géographique du back-office."""
        session_id, slug = session
        spec = DesignSpec(name="Chez Amara", country="SN", business_type="restaurant")
        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock, return_value=1), patch(
            "app.jobs.handlers.run_review_step", new_callable=AsyncMock
        ):
            await handle_generate(_payload(session_id, slug, spec))

        row = db.get_session(session_id)
        assert (row["country"], row["business_type"]) == ("SN", "restaurant")

    @pytest.mark.asyncio
    async def test_failure_propagates_so_the_queue_can_retry(self, session):
        """Le handler ne masque plus l'échec : c'est la file qui décide de réessayer.

        Absorber l'exception ici, comme le faisait la version en tâche asyncio,
        rendait tout échec définitif — la file ne pouvait pas savoir qu'il fallait
        retenter, ni distinguer une panne réseau passagère d'un refus définitif.
        """
        session_id, slug = session
        with patch(
            "app.jobs.handlers.run_code_step", new_callable=AsyncMock, side_effect=RuntimeError("Gemini KO")
        ), pytest.raises(RuntimeError, match="Gemini KO"):
            await handle_generate(_payload(session_id, slug, SPEC))

    @pytest.mark.asyncio
    async def test_exhausted_retries_mark_the_session_in_error(self, session):
        """Sans cela, le front interrogerait sans fin une génération qui ne reviendra pas."""
        session_id, slug = session
        job = {"session_id": session_id, "kind": "site.generate", "attempts": 3, "user_id": None}
        on_permanent_failure(job, "Gemini KO")

        row = db.get_session(session_id)
        assert row["status"] == "error"
        assert "Gemini KO" in (row["error"] or "")

    @pytest.mark.asyncio
    async def test_resuming_an_already_finished_session_is_a_no_op(self, session):
        """Un worker tué après coup ne doit pas facturer un second site au client."""
        session_id, slug = session
        db.add_artifact(session_id, "site", 1, {"version": 1})
        db.set_session_field(session_id, status="ready")

        with patch("app.jobs.handlers.run_code_step", new_callable=AsyncMock) as code:
            await handle_generate(_payload(session_id, slug, SPEC))

        code.assert_not_awaited()
