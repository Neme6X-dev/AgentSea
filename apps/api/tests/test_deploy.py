"""Tests de app/deploy.py : écriture versionnée et mise en ligne.

Ce module porte le mécanisme de retour arrière : `deploy_local` publiait toujours la
version la plus récente et ignorait la version demandée, ce qui rendait impossible de
revenir sur une version antérieure alors que toutes sont conservées sur disque.
"""
from __future__ import annotations

import pytest

from app.contracts import GeneratedSite
from app.deploy import deploy_local, live_dir, version_dir, write_site_files


@pytest.fixture
def site_dir(tmp_path, monkeypatch):
    """Isole les écritures dans un répertoire temporaire.

    `Settings` est un dataclass figé : on substitue l'objet entier dans le module plutôt
    que d'essayer d'en modifier un champ.
    """
    from types import SimpleNamespace

    import app.deploy as deploy_module

    monkeypatch.setattr(
        deploy_module,
        "settings",
        SimpleNamespace(sites_dir=tmp_path, public_base_url="http://127.0.0.1:8000"),
    )
    return tmp_path


def _write(slug: str, version: int, marker: str) -> None:
    write_site_files(
        slug,
        version,
        GeneratedSite(html=f"<html><body>{marker}</body></html>", css="body{}", js="// js"),
    )


def _live_html(slug: str) -> str:
    return (live_dir(slug) / "index.html").read_text(encoding="utf-8")


class TestWriteSiteFiles:
    def test_writes_the_site_and_its_beacon(self, site_dir):
        _write("resto", 1, "v1")
        d = version_dir("resto", 1)
        assert {p.name for p in d.iterdir()} == {
            "index.html",
            "style.css",
            "script.js",
            "jarvis-metrics.js",
        }

    def test_beacon_is_injected_by_the_platform(self, site_dir):
        """La mesure est écrite par la plateforme, jamais demandée au modèle.

        Le test l'affirme explicitement parce que c'est le point de l'exercice : un
        modèle omet ou déforme régulièrement ce genre de bloc, et une mesure absente
        sur un site sur cinq rend toutes les statistiques inexploitables. La version
        générée ici ne contient aucune balise de mesure — si le fichier est là, c'est
        que la plateforme l'a mis.
        """
        _write("resto", 1, "v1")
        beacon = version_dir("resto", 1) / "jarvis-metrics.js"
        assert beacon.exists()
        assert beacon.read_text(encoding="utf-8").strip()

    def test_versions_are_kept_side_by_side(self, site_dir):
        _write("resto", 1, "v1")
        _write("resto", 2, "v2")
        assert "v1" in (version_dir("resto", 1) / "index.html").read_text(encoding="utf-8")
        assert "v2" in (version_dir("resto", 2) / "index.html").read_text(encoding="utf-8")


class TestDeployLocal:
    def test_defaults_to_latest_version(self, site_dir):
        _write("resto", 1, "PREMIERE")
        _write("resto", 2, "DEUXIEME")
        url = deploy_local("resto")
        assert "DEUXIEME" in _live_html("resto")
        assert url.endswith("/sites/resto/live/")

    def test_publishes_the_requested_version(self, site_dir):
        _write("resto", 1, "PREMIERE")
        _write("resto", 2, "DEUXIEME")
        deploy_local("resto", 1)
        assert "PREMIERE" in _live_html("resto")

    def test_rollback_after_a_bad_release(self, site_dir):
        """Le scénario réel : on publie une v3 ratée, on revient sur la v2."""
        _write("resto", 1, "V1")
        _write("resto", 2, "V2")
        _write("resto", 3, "V3-CASSEE")
        deploy_local("resto", 3)
        assert "V3-CASSEE" in _live_html("resto")

        deploy_local("resto", 2)
        assert "V2" in _live_html("resto")
        assert "V3-CASSEE" not in _live_html("resto")
        # La version fautive reste sur disque : on peut la réexaminer, voire la republier.
        assert version_dir("resto", 3).is_dir()

    def test_version_beyond_ten_is_not_sorted_as_text(self, site_dir):
        """v10 doit être plus récente que v9 : un tri lexicographique dirait l'inverse."""
        for v in range(1, 11):
            _write("resto", v, f"VERSION-{v}")
        deploy_local("resto")
        assert "VERSION-10" in _live_html("resto")

    def test_unknown_version_raises(self, site_dir):
        _write("resto", 1, "V1")
        with pytest.raises(FileNotFoundError):
            deploy_local("resto", 99)

    def test_no_version_at_all_raises(self, site_dir):
        (site_dir / "vide").mkdir()
        with pytest.raises(FileNotFoundError):
            deploy_local("vide")
