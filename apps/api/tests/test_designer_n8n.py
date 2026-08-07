"""Designer n8n : extraction du DesignSpec et repli.

L'enjeu de ces tests n'est pas que n8n réponde bien — c'est qu'il puisse répondre
n'importe quoi sans jamais faire échouer une génération.
"""
from __future__ import annotations

import dataclasses
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import designer, designer_n8n
from app.config import Settings
from app.contracts import DesignSpec

SPEC_JSON = (
    '{"name": "Chez Amara", "tagline": "Cuisine ouest-africaine", "style": "moderne",'
    ' "sections": [{"id": "hero", "title": "Accueil", "content": "", "order": 0}]}'
)


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client_returning(payload):
    """Remplace httpx.AsyncClient par un double qui rend `payload`."""
    client = AsyncMock()
    client.__aenter__.return_value.post = AsyncMock(return_value=_Response(payload))
    return patch("app.agents.designer_n8n.httpx.AsyncClient", return_value=client)


def _configured(url="https://n8n.test/chat"):
    """`Settings` est gelé : on remplace l'objet entier plutôt qu'un de ses champs."""
    return patch("app.agents.designer_n8n.settings", dataclasses.replace(Settings(), n8n_designer_url=url))


class TestExtraction:
    def test_reads_json_buried_in_prose(self):
        data = designer_n8n._payload_to_spec_dict({"output": f"Voici la spec :\n{SPEC_JSON}\nBon courage !"})
        assert data["name"] == "Chez Amara"

    def test_reads_n8n_list_envelope(self):
        assert designer_n8n._payload_to_spec_dict([{"output": SPEC_JSON}])["name"] == "Chez Amara"

    def test_brace_inside_string_does_not_close_the_object(self):
        data = designer_n8n._payload_to_spec_dict('{"name": "a}b", "cta": "Réserver"}')
        assert data == {"name": "a}b", "cta": "Réserver"}

    def test_conversational_answer_yields_nothing(self):
        """Le webhook actuel répond en prose : il ne doit pas passer pour un spec."""
        assert designer_n8n._payload_to_spec_dict({"output": "Bonjour ! Quel est votre secteur ?"}) is None


class TestBuildDesignSpec:
    @pytest.mark.asyncio
    async def test_returns_none_when_url_not_configured(self):
        with _configured(""):
            assert await designer_n8n.build_design_spec("un restaurant") is None

    @pytest.mark.asyncio
    async def test_parses_a_valid_spec(self):
        with _configured(), _client_returning({"output": SPEC_JSON}):
            spec = await designer_n8n.build_design_spec("un restaurant")
        assert spec.name == "Chez Amara"

    @pytest.mark.asyncio
    async def test_adds_missing_hero_section(self):
        """Le codeur et la revue supposent une section hero : l'oubli amont est rattrapé."""
        with _configured(), _client_returning(
            {"output": '{"name": "Sans Hero", "sections": [{"id": "contact", "title": "Contact", "order": 1}]}'}
        ):
            spec = await designer_n8n.build_design_spec("un restaurant")
        assert spec.sections[0].id == "hero"

    @pytest.mark.asyncio
    async def test_network_failure_returns_none(self):
        client = AsyncMock()
        client.__aenter__.return_value.post = AsyncMock(side_effect=RuntimeError("524 timeout"))
        with _configured(), patch("app.agents.designer_n8n.httpx.AsyncClient", return_value=client):
            assert await designer_n8n.build_design_spec("un restaurant") is None

    @pytest.mark.asyncio
    async def test_malformed_spec_returns_none(self):
        with _configured(), _client_returning(
            {"output": '{"name": "X", "style": "psychedelique"}'}  # style hors énumération
        ):
            assert await designer_n8n.build_design_spec("un restaurant") is None


class TestDesignerFacade:
    @pytest.mark.asyncio
    async def test_prefers_n8n_when_it_answers(self):
        spec = DesignSpec(name="Depuis n8n")
        with patch("app.agents.designer.designer_n8n.build_design_spec", new_callable=AsyncMock, return_value=spec):
            result, source = await designer.build_design_spec("un restaurant")
        assert (result.name, source) == ("Depuis n8n", "n8n")

    @pytest.mark.asyncio
    async def test_falls_back_to_internal_designer(self):
        spec = DesignSpec(name="Depuis le mini")
        with patch(
            "app.agents.designer.designer_n8n.build_design_spec", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.agents.designer.designer_mini.build_design_spec", new_callable=AsyncMock, return_value=spec
        ):
            result, source = await designer.build_design_spec("un restaurant")
        assert (result.name, source) == ("Depuis le mini", "interne")

    @pytest.mark.asyncio
    async def test_redesign_never_asks_n8n(self):
        """n8n ne connaît pas la session : sur une refonte il produirait une autre marque."""
        previous = DesignSpec(name="Chez Amara")
        with patch("app.agents.designer.designer_n8n.build_design_spec", new_callable=AsyncMock) as n8n, patch(
            "app.agents.designer.designer_mini.build_design_spec",
            new_callable=AsyncMock,
            return_value=DesignSpec(name="Chez Amara"),
        ):
            _, source = await designer.build_design_spec("style sombre", previous=previous)
        n8n.assert_not_awaited()
        assert source == "interne"


class TestPlanExtraction:
    """Contrat réel du workflow : `{output, template_id, pages}`."""

    def test_reads_template_and_pages(self):
        plan = designer_n8n._extract_plan(
            {"output": "C'est prêt !", "template_id": "restaurant-chaleureux-02",
             "pages": ["accueil", "menu", "contact"]}
        )
        assert plan["template_id"] == "restaurant-chaleureux-02"
        assert [p["nom"] for p in plan["pages"]] == ["accueil", "menu", "contact"]

    def test_pages_arrive_as_a_serialised_json_array(self):
        """Contrat réel : `pages` est un tableau JSON **dans une chaîne**."""
        pages = json.dumps([
            {"nom": "Accueil (Home)", "slug": "accueil", "contenu": "Bienvenue, chez nous"},
            {"nom": "Menu", "slug": "menu-gastronomique-africain", "contenu": "Nos plats"},
        ], ensure_ascii=False)
        plan = designer_n8n._extract_plan({"template_id": "t", "pages": pages})
        # Découper sur les virgules produirait des fragments de JSON.
        assert [p["slug"] for p in plan["pages"]] == ["accueil", "menu-gastronomique-africain"]
        assert plan["pages"][0]["contenu"] == "Bienvenue, chez nous"

    def test_accepts_comma_separated_pages(self):
        plan = designer_n8n._extract_plan({"template_id": "x", "pages": "accueil, menu"})
        assert [p["nom"] for p in plan["pages"]] == ["accueil", "menu"]

    def test_object_output_is_not_dumped_into_the_chat(self):
        """Au tour final, `output` est le plan de construction, pas une phrase."""
        payload = [{"output": {"etapes": [{"id": "1", "nom": "Design System"}]},
                    "template_id": "restaurant-chaleureux-02", "pages": "[]"}]
        reply = designer_n8n._extract_reply(payload)
        assert "etapes" not in reply and "{" not in reply

    def test_reads_through_the_n8n_list_envelope(self):
        assert designer_n8n._extract_plan([{"template_id": "x", "pages": []}])["template_id"] == "x"

    def test_a_plain_question_carries_no_plan(self):
        """Tant que l'agent cadre, il n'y a rien à générer."""
        assert designer_n8n._extract_plan({"output": "Quel est votre secteur ?"}) is None

    @pytest.mark.asyncio
    async def test_chat_returns_the_plan(self):
        with _configured(), _client_returning(
            {"output": "Voilà.", "template_id": "restaurant-chaleureux-02", "pages": ["accueil"]}
        ):
            reply, spec, plan, erreur = await designer_n8n.chat("vas y", conversation_id="fil")
        assert erreur is None
        assert reply == "Voilà."
        assert spec is None  # ce n'est pas un DesignSpec, c'est un plan
        assert plan["template_id"] == "restaurant-chaleureux-02"


class TestSpecFromPlan:
    @pytest.mark.asyncio
    async def test_pages_decided_by_n8n_win(self):
        """L'utilisateur a validé ces pages en conversation : elles font autorité."""
        base = DesignSpec(name="Chez Amara", sections=[
            {"id": "hero", "title": "Accueil", "content": "c", "order": 0},
            {"id": "equipe", "title": "Équipe", "content": "c", "order": 1},
        ])
        with patch("app.agents.designer.designer_mini.build_design_spec",
                   new_callable=AsyncMock, return_value=base):
            spec = await designer.spec_from_plan(
                "un restaurant",
                {"template_id": "restaurant-chaleureux-02",
                 "pages": [{"slug": "accueil"}, {"slug": "menu"}, {"slug": "contact"}]},
            )
        assert [s.id for s in spec.sections] == ["hero", "services", "contact"]

    @pytest.mark.asyncio
    async def test_hero_is_always_present(self):
        base = DesignSpec(name="X")
        with patch("app.agents.designer.designer_mini.build_design_spec",
                   new_callable=AsyncMock, return_value=base):
            spec = await designer.spec_from_plan("x", {"template_id": "", "pages": [{"slug": "contact"}]})
        assert spec.sections[0].id == "hero"

    @pytest.mark.asyncio
    async def test_template_is_passed_to_the_internal_designer(self):
        base = DesignSpec(name="X")
        with patch("app.agents.designer.designer_mini.build_design_spec",
                   new_callable=AsyncMock, return_value=base) as mini:
            await designer.spec_from_plan("un restaurant", {"template_id": "restaurant-chaleureux-02", "pages": []})
        assert "restaurant-chaleureux-02" in mini.await_args.args[0]

    @pytest.mark.asyncio
    async def test_unknown_template_still_composes(self):
        """Un identifiant inconnu ne doit pas faire échouer la génération."""
        base = DesignSpec(name="X")
        with patch("app.agents.designer.designer_mini.build_design_spec",
                   new_callable=AsyncMock, return_value=base):
            spec = await designer.spec_from_plan("x", {"template_id": "nexiste-pas", "pages": [{"slug": "accueil"}]})
        assert spec.name == "X"


class TestRichPages:
    """Les fiches n8n portent le contenu rédigé avec l'utilisateur : il doit survivre."""

    PAGES = [
        {"nom": "Accueil (Home)", "slug": "accueil", "h1": "Savane Gourmande",
         "contenu": "Bienvenue chez Savane Gourmande, votre escale africaine.",
         "cta": ["Réserver une table en ligne", "Commander à emporter"]},
        {"nom": "Menu gastronomique", "slug": "menu-gastronomique-africain",
         "contenu": "Thieboudienne Royal, Poulet Yassa, Mafé de Bœuf.", "cta": ["Commander"]},
        {"nom": "Contact & Réservations", "slug": "contact-reservations",
         "contenu": ("Adresse : 45 Rue du Faubourg Saint-Martin, 75010 Paris\n"
                     "Téléphone : 01 23 45 67 89\nEmail : contact@savanegourmande.com")},
    ]

    def _plan(self):
        return {"template_id": "restaurant-chaleureux-02", "pages": self.PAGES}

    async def _spec(self):
        base = DesignSpec(name="Savane Gourmande")
        with patch("app.agents.designer.designer_mini.build_design_spec",
                   new_callable=AsyncMock, return_value=base):
            return await designer.spec_from_plan("un restaurant africain", self._plan())

    @pytest.mark.asyncio
    async def test_seo_slugs_map_to_known_sections(self):
        spec = await self._spec()
        assert [s.id for s in spec.sections] == ["hero", "services", "contact"]

    @pytest.mark.asyncio
    async def test_n8n_content_is_kept_verbatim(self):
        """Le texte a été validé en conversation : le réécrire le perdrait."""
        spec = await self._spec()
        assert "Savane Gourmande" in spec.sections[0].content
        assert "Thieboudienne" in spec.sections[1].content

    @pytest.mark.asyncio
    async def test_explicit_cta_wins(self):
        spec = await self._spec()
        assert spec.cta == "Réserver une table en ligne"

    @pytest.mark.asyncio
    async def test_contact_shown_in_the_content_lands_in_the_spec(self):
        """Sans ça, la validation signalerait ces coordonnées comme inventées."""
        spec = await self._spec()
        assert spec.contact.phone == "01 23 45 67 89"
        assert spec.contact.email == "contact@savanegourmande.com"
        assert "Faubourg Saint-Martin" in spec.contact.address

    @pytest.mark.asyncio
    async def test_pages_without_contact_leave_it_empty(self):
        """Aucun contact dans le contenu : le spec ne doit rien inventer non plus."""
        base = DesignSpec(name="X")
        with patch("app.agents.designer.designer_mini.build_design_spec",
                   new_callable=AsyncMock, return_value=base):
            spec = await designer.spec_from_plan(
                "x", {"template_id": "", "pages": [{"slug": "accueil", "contenu": "Bienvenue."}]}
            )
        assert spec.contact.phone == "" and spec.contact.email == ""


class TestFailureReasons:
    """Un workflow en erreur, un délai dépassé et une coupure réseau se corrigent à
    trois endroits différents : les confondre fait chercher du mauvais côté."""

    @pytest.mark.asyncio
    async def test_workflow_error_is_named_as_such(self):
        """Cas réel : n8n répond 500 {"message":"Error in workflow"}."""
        cli = AsyncMock()
        cli.__aenter__.return_value.post = AsyncMock(
            return_value=_Response({"message": "Error in workflow"}, status_code=500)
        )
        with _configured(), patch("app.agents.designer_n8n.httpx.AsyncClient", return_value=cli):
            reply, spec, plan, erreur = await designer_n8n.chat("go", conversation_id="fil")
        assert reply is None and spec is None and plan is None
        assert "HTTP 500" in erreur
        assert "workflow" in erreur.lower()

    @pytest.mark.asyncio
    async def test_timeout_is_distinguished_from_an_outage(self):
        import httpx as _httpx
        cli = AsyncMock()
        cli.__aenter__.return_value.post = AsyncMock(side_effect=_httpx.ReadTimeout("trop long"))
        with _configured(), patch("app.agents.designer_n8n.httpx.AsyncClient", return_value=cli):
            _, _, _, erreur = await designer_n8n.chat("go", conversation_id="fil")
        assert "pas répondu" in erreur

    @pytest.mark.asyncio
    async def test_network_failure_is_named_as_such(self):
        cli = AsyncMock()
        cli.__aenter__.return_value.post = AsyncMock(side_effect=RuntimeError("DNS"))
        with _configured(), patch("app.agents.designer_n8n.httpx.AsyncClient", return_value=cli):
            _, _, _, erreur = await designer_n8n.chat("go", conversation_id="fil")
        assert "injoignable" in erreur
