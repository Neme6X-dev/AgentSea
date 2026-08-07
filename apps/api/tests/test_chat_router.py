"""Chat de cadrage : relais n8n, fil de conversation, et panne côté n8n."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.contracts import DesignSpec
from app.main import app
from app.security import current_user

client = TestClient(app)
BASE = "/api/chat"


@pytest.fixture(autouse=True)
def authed():
    app.dependency_overrides[current_user] = lambda: {"id": 1, "email": "a@b.c", "name": "A"}
    yield
    app.dependency_overrides.clear()


def _chat(reply, spec=None, plan=None, erreur=None):
    return patch(
        "app.routers.chat.designer_n8n.chat",
        new_callable=AsyncMock,
        return_value=(reply, spec, plan, erreur),
    )


class TestChat:
    def test_relays_the_agent_question(self):
        with _chat("Quel est votre secteur d'activité ?"):
            r = client.post(BASE, json={"message": "bonjour"})
        assert r.status_code == 200
        body = r.json()
        assert body["reply"] == "Quel est votre secteur d'activité ?"
        # Pas de spec : l'agent cadre encore, il n'y a rien à générer.
        assert body["design_spec"] is None
        assert body["available"] is True

    def test_opens_a_conversation_id_on_first_message(self):
        with _chat("Bonjour !"):
            r = client.post(BASE, json={"message": "bonjour"})
        assert r.json()["conversation_id"]

    def test_keeps_the_conversation_id_across_turns(self):
        """Le fil doit survivre aux tours, sinon l'agent repose les mêmes questions."""
        with _chat("Et votre cible ?") as relay:
            r = client.post(BASE, json={"message": "un restaurant", "conversation_id": "fil-42"})
        assert r.json()["conversation_id"] == "fil-42"
        assert relay.await_args.kwargs["conversation_id"] == "fil-42"

    def test_returns_the_spec_once_the_agent_produced_one(self):
        spec = DesignSpec(name="Chez Amara")
        with _chat("Voici votre spécification.", spec):
            r = client.post(BASE, json={"message": "go"})
        assert r.json()["design_spec"]["name"] == "Chez Amara"

    def test_n8n_outage_is_not_an_http_error(self):
        """Le front doit pouvoir enchaîner sans cadrage plutôt que buter sur un échec."""
        with _chat(None, None, None, "Le workflow n8n a échoué (HTTP 500 — Error in workflow)."):
            r = client.post(BASE, json={"message": "bonjour"})
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is False
        # La cause exacte doit remonter : « injoignable » envoyait chercher le problème
        # côté réseau alors que le workflow amont répondait une erreur.
        assert "HTTP 500" in body["reply"]
        assert "designer interne" in body["reply"]

    def test_plan_is_composed_into_a_spec(self):
        """Contrat réel du workflow : `{output, template_id, pages}`, pas un DesignSpec."""
        plan = {"template_id": "restaurant-chaleureux-02", "pages": ["accueil", "menu", "contact"]}
        composed = DesignSpec(name="Chez Amara")
        with _chat("Voilà, c'est prêt !", None, plan), patch(
            "app.routers.chat.designer.spec_from_plan", new_callable=AsyncMock, return_value=composed
        ) as compose:
            r = client.post(BASE, json={"message": "vas y"})

        compose.assert_awaited_once()
        assert compose.await_args.args[1] == plan
        assert r.json()["design_spec"]["name"] == "Chez Amara"

    def test_a_failed_composition_does_not_lose_the_conversation(self):
        """Le cadrage a abouti : on rend la réponse, l'utilisateur garde la main."""
        plan = {"template_id": "inconnu", "pages": []}
        with _chat("C'est prêt !", None, plan), patch(
            "app.routers.chat.designer.spec_from_plan", new_callable=AsyncMock, side_effect=RuntimeError("LLM KO")
        ):
            r = client.post(BASE, json={"message": "vas y"})

        assert r.status_code == 200
        body = r.json()
        assert body["design_spec"] is None
        # La réponse de l'agent reste visible...
        assert body["reply"].startswith("C'est prêt !")
        # ... mais l'échec silencieux ne doit plus laisser l'utilisateur devant un
        # message qui promet une génération qui ne viendra pas : on lui dit quoi faire.
        assert "Générer le site" in body["reply"]

    def test_a_direct_spec_skips_composition(self):
        spec = DesignSpec(name="Direct")
        with _chat("ok", spec, {"template_id": "x", "pages": []}), patch(
            "app.routers.chat.designer.spec_from_plan", new_callable=AsyncMock
        ) as compose:
            r = client.post(BASE, json={"message": "vas y"})

        compose.assert_not_awaited()
        assert r.json()["design_spec"]["name"] == "Direct"

    def test_empty_message_is_rejected(self):
        r = client.post(BASE, json={"message": ""})
        assert r.status_code == 422

    def test_requires_authentication(self):
        app.dependency_overrides.clear()
        r = client.post(BASE, json={"message": "bonjour"})
        assert r.status_code == 401
