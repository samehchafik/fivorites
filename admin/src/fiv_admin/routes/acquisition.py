"""Le tableau d'acquisition : ce qui est collecté, dans quelle langue.

Toutes les routes exigent une session. Toutes sont en lecture seule.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from fiv_admin.deps import Config, Conn, CurrentUser, Search, get_summary_cache
from fiv_admin.media import DEFAULT_MEDIA, MEDIA, Media, language_label
from fiv_admin.queries import (
    SORTS,
    STATUSES,
    ItemsQuery,
    SummaryCache,
    fetch_detail,
    fetch_items,
    fetch_summary,
    observed_languages,
)

router = APIRouter()

MediaKey = Annotated[str, Query(pattern="^(tv|movie)$")]


def _media(key: str) -> Media:
    media = MEDIA.get(key)
    if media is None:  # pragma: no cover — le motif de Query l'a déjà filtré
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"univers inconnu : {key}")
    return media


def _require_catalog(media: Media) -> None:
    """Un univers sans inventaire n'a rien à afficher, et il vaut mieux le dire
    que renvoyer un tableau vide qu'on prendrait pour une collecte à zéro."""
    if media.catalog_table is None:
        raise HTTPException(status.HTTP_409_CONFLICT, media.unavailable_reason)


@router.get("/meta")
async def meta(user: CurrentUser, conn: Conn, settings: Config) -> dict[str, Any]:
    """De quoi remplir les sélecteurs : univers, langues, tris, états.

    Les langues sont l'union de ce que la collecte demande (la configuration)
    et de ce qu'on trouve réellement en base. La première liste dit ce qui est
    prévu, la seconde ce qui existe — et l'écart entre les deux est en soi une
    information : une langue configurée sans aucune ligne signale une collecte
    qui n'a pas encore tourné pour elle.
    """
    universes = []
    languages: list[str] = list(settings.languages)

    for media in MEDIA.values():
        available = media.catalog_table is not None
        if available:
            for code in await observed_languages(conn, media):
                if code not in languages:
                    languages.append(code)
        universes.append(
            {
                "key": media.key,
                "label": media.label,
                "partLabel": media.part_label,
                "available": available,
                "reason": media.unavailable_reason,
            }
        )

    return {
        "media": universes,
        "defaultMedia": DEFAULT_MEDIA,
        "languages": [
            {"code": code, "label": language_label(code)[0], "flag": language_label(code)[1]}
            for code in languages
        ],
        "sorts": list(SORTS),
        "statuses": list(STATUSES),
    }


@router.get("/acquisition/summary")
async def summary(
    user: CurrentUser,
    conn: Conn,
    cache: Annotated[SummaryCache, Depends(get_summary_cache)],
    media: MediaKey = DEFAULT_MEDIA,
) -> dict[str, Any]:
    target = _media(media)
    _require_catalog(target)

    cached = cache.get(target.key)
    if cached is not None:
        return cached

    result = await fetch_summary(conn, target)
    cache.put(target.key, result)
    return result


@router.get("/acquisition/items")
async def items(
    user: CurrentUser,
    conn: Conn,
    settings: Config,
    recherche: Search,
    lang: str = Query(default="fr-FR", max_length=16),
    media: MediaKey = DEFAULT_MEDIA,
    status_filter: str = Query(default="all", alias="status"),
    search: str | None = Query(default=None, max_length=120),
    minPopularity: float | None = Query(default=None, ge=0),
    sort: str = Query(default="popularity"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    target = _media(media)
    _require_catalog(target)

    if sort not in SORTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"tri inconnu : {sort}")
    if status_filter not in STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"état inconnu : {status_filter}"
        )

    query = ItemsQuery(
        media=target,
        lang=lang,
        status=status_filter,
        search=(search or "").strip() or None,
        min_popularity=minPopularity,
        sort=sort,
        descending=order == "desc",
        page=page,
        page_size=pageSize,
    )

    # Une recherche passe par Elasticsearch : il classe les meilleurs ids —
    # tous titres, toutes langues, catalogue entier — et le SQL applique
    # ensuite le filtre d'état, trop mouvant pour être indexé, puis pagine
    # dans l'ordre de pertinence. Le total est donc borné par le plafond
    # d'ids (voir `ACQUISITION_MAX_IDS`) : une recherche n'est pas une liste
    # à parcourir, elle se précise. ES absent = l'ILIKE historique.
    moteur = "sql"
    rows: list[dict[str, Any]] = []
    total = 0
    if query.search:
        page_es = await recherche.ids_acquisition(
            target, query.search, min_popularity=query.min_popularity
        )
        if page_es is not None:
            rows, total = await fetch_items(conn, query, ids=page_es.ids)
            moteur = "es"
    if moteur == "sql":
        rows, total = await fetch_items(conn, query)

    return {
        "items": rows,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "lang": lang,
        "searchEngine": moteur if query.search else None,
        # Les colonnes de langue du tableau : les langues configurées d'abord,
        # dans leur ordre, puis celles qui n'existent qu'en base.
        "languages": list(settings.languages),
        # Un tri par fraîcheur ne peut porter que sur ce qui a été regardé : la
        # jointure y devient interne. Le front l'affiche plutôt que de laisser
        # croire à un catalogue amputé.
        "truncatedToFetched": sort == "fetched",
    }


@router.get("/acquisition/items/{work_id}")
async def item_detail(
    user: CurrentUser,
    conn: Conn,
    work_id: int,
    media: MediaKey = DEFAULT_MEDIA,
) -> dict[str, Any]:
    target = _media(media)
    _require_catalog(target)

    detail = await fetch_detail(conn, target, work_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"introuvable au catalogue : {work_id}")
    return detail
