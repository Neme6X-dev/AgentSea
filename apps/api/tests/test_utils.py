"""Tests de utils.py : slugify / unique_slug."""
from __future__ import annotations

from app.utils import slugify, unique_slug


class TestSlugify:
    def test_latin_simple(self):
        assert slugify("Chez Amara") == "chez-amara"

    def test_accents_removed(self):
        assert slugify("Réservation édition") == "reservation-edition"

    def test_max_words(self):
        assert slugify("A B C D E F", max_words=4) == "a-b-c-d"

    def test_limit_length(self):
        assert len(slugify("x-" * 100)) <= 60

    def test_punctuation_removed(self):
        assert slugify("Resto !!! Très; Bien,") == "resto-tres-bien"

    def test_empty_fallback(self):
        assert slugify("!!!" [0:] if False else "???") == "site"

    def test_non_ascii_stripped(self):
        assert slugify("カフェ 東京") == "site"


class TestUniqueSlug:
    def test_returns_base_if_free(self):
        assert unique_slug("Cabinet Falcon", set()) == "cabinet-falcon"

    def test_appends_suffix_on_collision(self):
        assert unique_slug("Cabinet Falcon 3", {"cabinet-falcon-3"}) == "cabinet-falcon-3-1"

    def test_increments_counter(self):
        taken = {"cabinet", "cabinet-1"}
        assert unique_slug("Cabinet", taken) == "cabinet-2"