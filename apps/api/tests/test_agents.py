"""Tests des agents : coder, reviewer, designer_mini (Gemini mocké)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents import coder, designer_mini, reviewer
from app.contracts import DesignSpec, GeneratedSite

SPEC = DesignSpec(name="Chez Amara", tagline="Restaurant africain", language="fr")
SITE = GeneratedSite(
    html="<!DOCTYPE html><html lang=\"fr\"><body><h1>Chez Amara</h1></body></html>",
    css="body{color:#000}",
    js="",
)


class TestCoderAgent:
    @pytest.mark.asyncio
    async def test_build_site_returns_generated_site(self):
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {"html": SITE.html, "css": SITE.css, "js": ""}
            site = await coder.build_site(SPEC)
            assert isinstance(site, GeneratedSite)
            assert "Chez Amara" in site.html

    @pytest.mark.asyncio
    async def test_retries_on_invalid_payload(self):
        from app.gemini import LLMError
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock, \
                patch.object(coder.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            # html trop long => _normalize_site lève ValueError à chaque tentative
            mock.return_value = {"html": "x" * (200_001), "css": "", "js": ""}
            with pytest.raises(LLMError):
                await coder.build_site(SPEC)
            assert mock.await_count == coder._MAX_ATTEMPTS
            # Une pause sépare chaque tentative : sans elle, une coupure réseau
            # passagère faisait échouer les essais en rafale.
            assert sleep.await_count == coder._MAX_ATTEMPTS - 1

    @pytest.mark.asyncio
    async def test_succeeds_on_retry_after_transient_error(self):
        from app.gemini import LLMError
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock, \
                patch.object(coder.asyncio, "sleep", new_callable=AsyncMock), \
                patch.object(coder, "validate_site", return_value=[]):
            mock.side_effect = [
                LLMError("Réseau: échec de l'appel Gemini"),
                {"html": SITE.html, "css": SITE.css, "js": ""},
            ]
            site = await coder.build_site(SPEC)
            assert "Chez Amara" in site.html


class TestCoderValidation:
    """Le codeur doit corriger ses propres écarts à la spécification avant de livrer."""

    @pytest.mark.asyncio
    async def test_violations_trigger_one_correction_pass(self):
        from app.agents.validation import Issue
        payload = {"html": SITE.html, "css": SITE.css, "js": ""}
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock, \
                patch.object(coder, "validate_site") as validate:
            mock.return_value = payload
            validate.side_effect = [
                [Issue("palette.primary", "La couleur primary du spec (#b23a17) n'apparaît pas dans le CSS.")],
                [],
            ]
            await coder.build_site(SPEC)

        assert mock.await_count == 2, "aucune passe de correction n'a été demandée"
        correction = mock.await_args.args[1]
        # Le modèle reçoit le manquement exact, pas un reproche générique.
        assert "#b23a17" in correction
        assert "Corrections obligatoires" in correction

    @pytest.mark.asyncio
    async def test_ships_after_exhausting_the_correction_budget(self):
        """Un défaut de qualité ne doit pas transformer la génération en échec.

        Le rapport de revue les remontera, et le garde-fou de publication bloquera ce qui
        est réellement dangereux : livrer un site perfectible vaut mieux qu'un 500.
        """
        from app.agents.validation import Issue
        issues = [Issue("sections.missing:equipe", "La section « L'équipe » du spec est absente.")]
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock, \
                patch.object(coder, "validate_site", return_value=issues):
            mock.return_value = {"html": SITE.html, "css": SITE.css, "js": ""}
            site = await coder.build_site(SPEC)

        assert isinstance(site, GeneratedSite)
        assert mock.await_count == coder._MAX_CORRECTIONS + 1

    @pytest.mark.asyncio
    async def test_validation_uses_the_effective_spec(self):
        """Lors d'une refonte, la validation porte sur le NOUVEAU spec.

        La valider contre l'ancien rejetterait la refonte pour infidélité à une palette
        qu'on vient justement de remplacer.
        """
        nouveau = DesignSpec(name="Chez Amara", tagline="Sombre", language="fr")
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock, \
                patch.object(coder, "validate_site", return_value=[]) as validate:
            mock.return_value = {"html": SITE.html, "css": SITE.css, "js": ""}
            await coder.build_site(nouveau)
        assert validate.call_args.args[1] is nouveau

    @pytest.mark.asyncio
    async def test_pass_current_site_for_instruction(self):
        with patch.object(coder.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {"html": SITE.html, "css": SITE.css, "js": ""}
            await coder.build_site(SPEC, instruction="change les couleurs", current_site=SITE)
            user_msg = mock.await_args.args[1]
            assert "Site actuel" in user_msg
            assert "Instruction de modification" in user_msg


class TestReviewerAgent:
    @pytest.mark.asyncio
    async def test_merges_sast_and_llm(self):
        with patch.object(reviewer.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "score": 90,
                "verdict": "pass",
                "dimensions": {"security": 95, "design_fidelity": 90, "accessibility": 88, "responsiveness": 92, "content": 90},
                "findings": [],
                "summary": "Bon site.",
            }
            report = await reviewer.review_site(SITE, SPEC)
            assert report.verdict in ("pass", "warn", "fail")
            assert 0 <= report.score <= 100

    @pytest.mark.asyncio
    async def test_sast_suffices_when_llm_fails(self):
        from app.gemini import LLMError
        with patch.object(reviewer.gemini, "complete_json", new_callable=AsyncMock, side_effect=LLMError("down")):
            report = await reviewer.review_site(SITE, SPEC)
            assert report.llm_available is False
            assert "partielle" in report.summary
            assert isinstance(report.findings, list)

    @pytest.mark.asyncio
    async def test_clean_site_is_not_failed_when_llm_unavailable(self):
        """Une panne de Gemini ne doit pas condamner un site sain.

        Les dimensions par défaut valaient 0, donc le repli « SAST seul » notait 0/100
        et rendait `fail` un site sans le moindre finding — ce qui bloquerait sa
        publication.
        """
        from app.gemini import LLMError
        clean = GeneratedSite(
            html=(
                '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<link rel="stylesheet" href="style.css"></head><body><h1>Chez Amara</h1>'
                '<script src="script.js"></script></body></html>'
            ),
            css="body{color:#000}",
            js="document.addEventListener('click', function () {});",
        )
        with patch.object(reviewer.gemini, "complete_json", new_callable=AsyncMock, side_effect=LLMError("down")):
            report = await reviewer.review_site(clean, SPEC)
        assert report.verdict != "fail"
        assert report.score >= 55

    @pytest.mark.asyncio
    async def test_out_of_schema_category_does_not_crash(self):
        """Gemini recopie parfois l'énumération du schéma au lieu de choisir.

        Ce cas remontait en ValueError non rattrapée, donc en HTTP 500 sur
        /api/agents/review, cassant le workflow n8n en milieu de chaîne.
        """
        with patch.object(reviewer.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "score": 80,
                "verdict": "pass",
                "dimensions": {"security": 80, "design_fidelity": 80, "accessibility": 80,
                               "responsiveness": 80, "content": 80},
                "findings": [{
                    "severity": "medium", "category": "responsive|accessibility",
                    "title": "Contraste faible", "detail": "", "fix": "", "file": "style.css",
                }],
                "summary": "Correct.",
            }
            report = await reviewer.review_site(SITE, SPEC)
        assert report.llm_available is True
        assert mock.await_count == 1  # normalisé du premier coup, sans retry
        assert report.findings[-1].category in ("responsive", "accessibility")

    @pytest.mark.asyncio
    async def test_llm_findings_do_not_double_penalize(self):
        """Le LLM a déjà tenu compte de ses constats en notant les dimensions.

        Les repénaliser sanctionnait deux fois un reviewer précis, et avantageait donc
        mécaniquement un reviewer laconique.
        """
        base = {
            "score": 80, "verdict": "warn",
            "dimensions": {"security": 90, "design_fidelity": 90, "accessibility": 90,
                           "responsiveness": 90, "content": 90},
            "summary": "ok",
        }
        with patch.object(reviewer.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {**base, "findings": []}
            sans = await reviewer.review_site(SITE, SPEC)
        with patch.object(reviewer.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {**base, "findings": [
                {"severity": "medium", "category": "quality", "title": "Texte générique",
                 "detail": "", "fix": "", "file": "index.html"},
            ]}
            avec = await reviewer.review_site(SITE, SPEC)
        assert avec.dimensions.content == sans.dimensions.content

    def test_score_floor_on_critical(self):
        from app.contracts import ReviewFinding
        findings = [
            ReviewFinding(severity="critical", category="security", title="XSS", detail="", fix="", file="")
        ]
        dims = reviewer.ReviewDimensions(security=100, design_fidelity=100, accessibility=100, responsiveness=100, content=100)
        score, verdict = reviewer._score(findings, dims)
        assert score <= 50
        assert verdict == "fail"


class TestDesignerMini:
    @pytest.mark.asyncio
    async def test_build_design_spec(self):
        with patch.object(designer_mini.gemini, "complete_json", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "name": "Chez Amara",
                "tagline": "Restaurant africain",
                "business_type": "restaurant",
                "sections": [{"id": "apropos", "title": "À propos", "content": "text", "order": 1}],
                "contact": {"phone": "", "email": "", "address": "", "hours": ""},
            }
            spec = await designer_mini.build_design_spec("restaurant africain")
            assert isinstance(spec, DesignSpec)
            assert any(s.id == "hero" for s in spec.sections)

    @pytest.mark.asyncio
    async def test_retries_on_invalid(self):
        with patch.object(designer_mini.gemini, "complete_json", new_callable=AsyncMock, side_effect=Exception("bad")):
            with pytest.raises(Exception):
                await designer_mini.build_design_spec("x")


class TestGeminiTruncation:
    """Une réponse coupée par le plafond de sortie doit se dire, pas se déguiser."""

    @pytest.mark.asyncio
    async def test_max_tokens_raises_a_clear_error(self):
        from unittest.mock import patch, AsyncMock
        from app.gemini import GeminiClient, LLMError, _KeyPool

        class _Resp:
            status_code = 200
            def json(self):
                return {"candidates": [{
                    "finishReason": "MAX_TOKENS",
                    "content": {"parts": [{"text": '{"html": "<div>coupe au milieu'}]},
                }]}

        import dataclasses
        from app.config import Settings

        cli = AsyncMock(); cli.__aenter__.return_value.post = AsyncMock(return_value=_Resp())
        # `Settings` est gelé : on remplace l'objet entier plutôt qu'un de ses champs.
        # La clé factice est indispensable : sans elle, le client échoue sur « clé
        # manquante » avant même d'appeler l'API, et le test passait auparavant
        # uniquement parce qu'un .env local en fournissait une — une dépendance à
        # l'environnement de la machine qui n'a rien à faire dans une suite de tests.
        faux = dataclasses.replace(Settings(), gemini_mock=False, gemini_api_keys=["cle-de-test"])
        g = GeminiClient.__new__(GeminiClient)
        g._keys = _KeyPool(["cle-de-test"])
        with patch("app.gemini.settings", faux), \
             patch("app.gemini.httpx.AsyncClient", return_value=cli):
            with pytest.raises(LLMError) as e:
                await g.complete("s", "u")
        # Le message doit nommer la cause et le réglage, pas un « JSON invalide ».
        assert "tronqu" in str(e.value).lower()
        assert "GEMINI_MAX_OUTPUT_TOKENS" in str(e.value)

    def test_request_declares_an_output_ceiling(self):
        from app.config import settings
        assert settings.gemini_max_output_tokens >= 16384
