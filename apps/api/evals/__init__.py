"""Harnais d'évaluation des agents (hors `tests/` : ne tourne pas dans la CI par défaut).

- `run_detection` : le SAST identifie-t-il les vulnérabilités ? (0 appel LLM)
- `run_generation` : le codeur produit-il du bon code ?
- `run_edit` : les modifications s'intègrent-elles correctement au site existant ?
"""
