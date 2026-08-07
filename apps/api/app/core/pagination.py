"""Pagination partagée par les listes du back-office.

Les listes d'administration (utilisateurs, sites, travaux, journal d'audit) grossissent
sans limite. Une seule d'entre elles renvoyée en entier suffirait à faire tomber le
dashboard le jour où la plateforme marche — c'est-à-dire au pire moment.

Le modèle est volontairement à décalage (`offset`) et non à curseur : les écrans
concernés ont besoin de sauter à une page arbitraire et d'afficher un total, ce qu'un
curseur ne permet pas. Les volumes en jeu (dizaines de milliers de lignes, index sur
les colonnes de tri) restent très loin du seuil où le décalage devient coûteux.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True)
class PageParams:
    """Paramètres de pagination normalisés, issus de la requête."""

    page: int = 1
    size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


def page_params(
    page: int = Query(1, ge=1, description="Numéro de page, à partir de 1."),
    size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description=f"Éléments par page (max {MAX_PAGE_SIZE}).",
    ),
) -> PageParams:
    """Dépendance FastAPI : `params: Annotated[PageParams, Depends(page_params)]`.

    Le plafond est imposé côté serveur et non seulement documenté : `size=100000` est
    la première chose qu'essaie un script d'export, et c'est exactement la requête qui
    saturerait la base.
    """
    return PageParams(page=page, size=size)


class Page(BaseModel, Generic[T]):
    """Enveloppe de réponse paginée.

    `total` est renvoyé parce que le back-office affiche « 1 240 utilisateurs » et
    doit dimensionner sa navigation. Le surcoût d'un `COUNT(*)` est négligeable sur des
    tables indexées, et l'information est trop utile pour être sacrifiée.
    """

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = DEFAULT_PAGE_SIZE
    pages: int = 0

    @classmethod
    def build(cls, items: list[Any], total: int, params: PageParams) -> "Page":
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=max(1, -(-total // params.size)) if total else 0,
        )
