"""Utilitaires généraux."""
from __future__ import annotations

import random
import re
import unicodedata


def slugify(text: str, max_words: int = 4) -> str:
    """Génère un slug lisible depuis un texte (nom d'entreprise, prompt…)."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    words = [w for w in re.split(r"[^a-zA-Z0-9]+", ascii_text.lower()) if w]
    if not words:
        words = ["site"]
    base = "-".join(words[:max_words])
    return base[:60].rstrip("-") or "site"


def unique_slug(text: str, taken: set[str]) -> str:
    """Slug unique (ajoute un suffixe court si collision)."""
    base = slugify(text)
    candidate = base
    counter = 0
    while candidate in taken:
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate
