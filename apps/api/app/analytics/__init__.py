"""Collecte d'événements et agrégations du back-office.

`events` écrit, `queries` lit. La séparation est stricte : aucun chemin d'écriture
ne dépend d'une agrégation, aucune agrégation n'écrit — c'est ce qui permet de
déplacer un jour les lectures sur un réplica sans toucher au produit.
"""
from app.analytics import events, queries

__all__ = ["events", "queries"]
