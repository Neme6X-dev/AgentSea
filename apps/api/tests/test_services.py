"""Tests de services.py : étapes du pipeline et vue de session (agents mockés)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app import db
from app.contracts import DesignSpec, GeneratedSite, ReviewReport, ReviewFinding, ReviewDimensions
from app.services import build_session_view, get_latest_design_spec, run_code_step, run_deploy_step, run_review_step

SPEC = DesignSpec(name="Chez Amara", tagline="Restaurant africain", language="fr")
SITE = GeneratedSite(html="<h1>Chez Amara</h1>", css="body{}", js="")


@pytest.fixture
def session():
    u = db.create_user("s@example.com")
    return db.create_session(u["id"], "restaurant africain", "chez-amara")


@pytest.fixture
def report() -> ReviewReport:
    return ReviewReport(
        score=88,
        verdict="pass",
        dimensions=ReviewDimensions(security=95, design_fidelity=90, accessibility=88, responsiveness=92, content=90),
        findings=[ReviewFinding(severity="info", category="quality", title="Note", detail="", fix="", file="")],
        summary="Bien.",
    )


class TestPipelineSteps:
    @pytest.mark.asyncio
    async def test_code_step_writes_version(self, session, tmp_path):
        with patch("app.services.coder.build_site", new_callable=AsyncMock) as mock, patch(
            "app.deploy.version_dir", return_value=tmp_path
        ):
            mock.return_value = SITE
            version = await run_code_step(session, "chez-amara", SPEC)
            assert version == 1
            assert (tmp_path / "index.html").exists()
            s = db.get_session(session)
            assert s["steps"][-1]["step"] == "code"

    @pytest.mark.asyncio
    async def test_review_step_stores_report(self, session, report, tmp_path):
        (tmp_path / "index.html").write_text(SITE.html, encoding="utf-8")
        (tmp_path / "style.css").write_text(SITE.css, encoding="utf-8")
        (tmp_path / "script.js").write_text("", encoding="utf-8")
        with patch("app.services.reviewer.review_site", new_callable=AsyncMock) as mock, patch(
            "app.services.version_dir", return_value=tmp_path
        ), patch("app.services.get_latest_design_spec", return_value=SPEC):
            mock.return_value = report
            out = await run_review_step(session, "chez-amara-review", 1)
            assert out.score == 88
            arts = db.get_artifacts(session, "report")
            assert arts and arts[0]["payload"]["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_deploy_step_sets_url(self, session, tmp_path):
        from app.config import Settings
        import dataclasses
        fake = dataclasses.replace(Settings(), vps_host="", vps_user="")
        (tmp_path / "v1").mkdir()
        for fname, content in (("index.html", SITE.html), ("style.css", SITE.css), ("script.js", SITE.js)):
            (tmp_path / "v1" / fname).write_text(content, encoding="utf-8")
        with patch("app.services.deploy_local", return_value="http://localhost:8000/sites/x/live/") as mock_deploy, patch(
            "app.services.settings", fake
        ), patch("app.deploy.slug_dir", return_value=tmp_path):
            url = await run_deploy_step(session, "chez-amara-deploy", 1)
            assert url == "http://localhost:8000/sites/x/live/"
            assert db.get_session(session)["status"] == "deployed"


class TestDesignSpec:
    def test_get_latest_design_spec(self, session):
        db.add_artifact(session, "design_spec", 1, SPEC.model_dump())
        spec = get_latest_design_spec(session)
        assert spec is not None
        assert spec.name == "Chez Amara"

    def test_ignores_invalid_payload(self, session):
        db.add_artifact(session, "design_spec", 1, {"name": "x", "sections": "nope"})
        assert get_latest_design_spec(session) is None

    def test_no_spec(self, session):
        assert get_latest_design_spec(session) is None


class TestSessionView:
    def test_build_view_versions(self, session):
        db.add_artifact(session, "site", 1, {})
        db.add_artifact(session, "site", 2, {})
        view = build_session_view(db.get_session(session))
        assert view.versions == ["v1", "v2"]
        assert view.status == "pending"
        assert view.site_url is None

    def test_build_view_report(self, session, report):
        db.add_artifact(session, "report", 1, report.model_dump())
        view = build_session_view(db.get_session(session))
        assert view.report is not None
        assert view.report.score == 88