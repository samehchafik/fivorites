"""La navigation dans le catalogue collecté : grille, fiche, saisons.

Une seule route écrit, et elle n'écrit rien de métier : `refresh` recalcule la
projection d'affichage. Rien ici ne déclenche de collecte — engager deux
millions de requêtes TMDB depuis un bouton de page web n'est pas une commodité,
c'est un accident qui attend son heure.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from fiv_admin.catalog import (
    CARD_SORTS,
    CardQuery,
    cards_state,
    fetch_cards,
    fetch_season,
    fetch_work,
    refresh_cards,
)
from fiv_admin.deps import Conn, CurrentUser

router = APIRouter()


@router.get("/catalog/cards")
async def cards(
    user: CurrentUser,
    conn: Conn,
    lang: str = Query(default="fr-FR", max_length=16),
    search: str | None = Query(default=None, max_length=120),
    minPopularity: float | None = Query(default=None, ge=0),
    sort: str = Query(default="air_date"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    sort2: str | None = Query(default=None),
    order2: str = Query(default="desc", pattern="^(asc|desc)$"),
    withPoster: bool = Query(default=False),
    withOverview: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=24, ge=1, le=96),
) -> dict[str, Any]:
    for key in (sort, sort2):
        if key is not None and key not in CARD_SORTS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"tri inconnu : {key}")

    rows, total = await fetch_cards(
        conn,
        CardQuery(
            lang=lang,
            search=(search or "").strip() or None,
            min_popularity=minPopularity,
            sort=sort,
            descending=order == "desc",
            sort2=sort2 or None,
            descending2=order2 == "desc",
            with_poster=withPoster,
            with_overview=withOverview,
            page=page,
            page_size=pageSize,
        ),
    )
    return {
        "items": rows,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "lang": lang,
        # L'état de la projection accompagne chaque page : une grille vide a
        # deux causes très différentes — rien de collecté, ou une projection
        # jamais rafraîchie — et le front doit pouvoir les distinguer.
        "projection": await cards_state(conn),
    }


@router.get("/catalog/works/{work_id}")
async def work(
    user: CurrentUser,
    conn: Conn,
    work_id: int,
    lang: str = Query(default="fr-FR", max_length=16),
) -> dict[str, Any]:
    detail = await fetch_work(conn, work_id, lang)
    if detail is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"aucune fiche collectée pour {work_id} — la série est peut-être au "
            "catalogue sans avoir encore été téléchargée.",
        )
    return detail


@router.get("/catalog/works/{work_id}/seasons/{season_number}")
async def season(
    user: CurrentUser,
    conn: Conn,
    work_id: int,
    season_number: int,
    lang: str = Query(default="fr-FR", max_length=16),
) -> dict[str, Any]:
    detail = await fetch_season(conn, work_id, season_number, lang)
    if detail is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"saison {season_number} non collectée en {lang}",
        )
    return detail


@router.post("/catalog/refresh")
async def refresh(user: CurrentUser, conn: Conn) -> dict[str, Any]:
    """Recalcule la projection des vignettes depuis le brut."""
    total = await refresh_cards(conn)
    return {"projected": total, **await cards_state(conn)}
