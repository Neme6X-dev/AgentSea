"""Catalogue de templates : sélection par secteur et injection dans le codeur."""
from __future__ import annotations

from app.agents import coder, templates
from app.contracts import DesignSpec, GeneratedSite


class TestCatalog:
    def test_catalog_is_loaded(self):
        assert len(templates.catalog()) >= 1
        assert all(fiche.get("id") for fiche in templates.catalog())


class TestBestMatch:
    def test_matches_on_business_type(self):
        spec = DesignSpec(name="Chez Amara", business_type="restaurant")
        assert templates.best_match(spec)["secteur"] in {"restauration", "hotellerie-restauration"}

    def test_unknown_sector_gets_no_template(self):
        """Une association ne doit pas hériter d'une structure d'e-commerce."""
        spec = DesignSpec(name="Les Jardins", business_type="association")
        assert templates.best_match(spec) is None

    def test_tone_breaks_the_tie_within_a_sector(self):
        chaleureux = DesignSpec(name="A", business_type="restaurant", tone="chaleureux")
        assert templates.best_match(chaleureux)["style"] == "chaleureux"

    def test_selection_is_deterministic(self):
        spec = DesignSpec(name="A", business_type="cabinet")
        assert templates.best_match(spec)["id"] == templates.best_match(spec)["id"]


class TestReferenceBlock:
    def test_block_carries_structure_not_markup(self):
        spec = DesignSpec(name="Chez Amara", business_type="restaurant")
        block = templates.reference_block(spec)
        assert "Template de référence" in block
        assert "Composants caractéristiques" in block
        # C'est un repère de structure : aucun HTML ne doit fuiter dans le prompt.
        assert "<div" not in block and "<html" not in block

    def test_empty_when_no_template_fits(self):
        spec = DesignSpec(name="Les Jardins", business_type="association")
        assert templates.reference_block(spec) == ""


class TestCoderIntegration:
    def test_template_is_injected_on_creation(self):
        spec = DesignSpec(name="Chez Amara", business_type="restaurant")
        message = coder._build_user_message(spec)
        assert "Template de référence" in message

    def test_template_is_omitted_on_edit(self):
        """En retouche, le site actuel fait référence — un template le ferait remanier."""
        spec = DesignSpec(name="Chez Amara", business_type="restaurant")
        site = GeneratedSite(html="<html></html>", css="", js="")
        message = coder._build_user_message(spec, instruction="Ajoute les horaires", current_site=site)
        assert "Template de référence" not in message

    def test_designspec_still_leads(self):
        """Le template ne doit pas prendre le pas sur le contrat d'entrée du codeur."""
        spec = DesignSpec(name="Chez Amara", business_type="restaurant")
        message = coder._build_user_message(spec)
        assert message.index("## DesignSpec") < message.index("## Template de référence")
