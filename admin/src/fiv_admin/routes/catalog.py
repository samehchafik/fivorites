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
    fetch_rich,
    fetch_season,
    fetch_work,
    genres_disponibles,
    refresh_cards,
)
from fiv_admin.deps import Conn, CurrentUser, Search
from fiv_admin.media import DEFAULT_MEDIA, MEDIA

router = APIRouter()

# Le filtre par genre, en paramètre répété. Sorti en constante parce qu'un
# `Query(...)` écrit dans un défaut d'argument est un appel évalué à l'import,
# et qu'une liste mutable partagée entre requêtes est le genre de piège qui ne
# se voit qu'en production.
GENRES_QUERY = Query(default=[], description="Genres retenus, en OU. Répétable.")


def _media(cle: str) -> str:
    """Valide l'univers demandé. Liste fermée : la clé vient de la requête HTTP
    et sert à choisir un nom de vue — une valeur libre y serait une injection."""
    if cle not in MEDIA:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"univers inconnu : {cle} (attendus : {', '.join(MEDIA)})",
        )
    if not MEDIA[cle].disponible:
        raise HTTPException(status.HTTP_409_CONFLICT, MEDIA[cle].unavailable_reason)
    return cle


@router.get("/catalog/cards")
async def cards(
    user: CurrentUser,
    conn: Conn,
    recherche: Search,
    lang: str = Query(default="fr-FR", max_length=16),
    media: str = Query(default=DEFAULT_MEDIA, max_length=16),
    search: str | None = Query(default=None, max_length=120),
    minPopularity: float | None = Query(default=None, ge=0),
    sort: str = Query(default="air_date"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    sort2: str | None = Query(default=None),
    order2: str = Query(default="desc", pattern="^(asc|desc)$"),
    withPoster: bool = Query(default=False),
    withOverview: bool = Query(default=False),
    # Répété plutôt que séparé par des virgules : plusieurs genres de TMDB en
    # contiennent des caractères qu'un découpage maison finirait par mal
    # traiter (« Action & Adventure », « Sci-Fi & Fantasy »). `?genres=Comédie
    # &genres=Drame` ne demande aucune analyse.
    genres: list[str] = GENRES_QUERY,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=24, ge=1, le=96),
) -> dict[str, Any]:
    for key in (sort, sort2):
        if key is not None and key not in CARD_SORTS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"tri inconnu : {key}")

    q = CardQuery(
        lang=lang,
        media=_media(media),
        search=(search or "").strip() or None,
        min_popularity=minPopularity,
        sort=sort,
        descending=order == "desc",
        sort2=sort2 or None,
        descending2=order2 == "desc",
        with_poster=withPoster,
        with_overview=withOverview,
        genres=tuple(g for g in genres if g.strip()),
        page=page,
        page_size=pageSize,
    )

    # Toute liste vient d'Elasticsearch quand il répond — la frappe comme le
    # parcours. Une frappe est classée par pertinence (tous titres, toutes
    # langues ; le tri demandé est ignoré : chercher, c'est demander la
    # pertinence). Un parcours garde les tris et filtres de la grille, servis
    # par les doc values — et le total arrive avec la page, là où le SQL
    # payait un `count(*)` complet à chaque affichage. Dans les deux cas ES ne
    # rend que des ids : Postgres hydrate les vignettes, comme toujours. ES
    # muet = tout en SQL, comme avant.
    if q.search:
        page_es = await recherche.page_cards(
            MEDIA[q.media],
            q.search,
            with_poster=q.with_poster,
            with_overview=q.with_overview,
            min_popularity=q.min_popularity,
            genres=q.genres,
            page=q.page,
            page_size=q.page_size,
        )
    else:
        page_es = await recherche.liste_cards(
            MEDIA[q.media],
            q.criteria,
            with_poster=q.with_poster,
            with_overview=q.with_overview,
            min_popularity=q.min_popularity,
            genres=q.genres,
            page=q.page,
            page_size=q.page_size,
        )
    if page_es is not None:
        rows, _ = await fetch_cards(conn, q, ids=page_es.ids)
        total = page_es.total
        moteur = "es"
    else:
        rows, total = await fetch_cards(conn, q)
        moteur = "sql"

    return {
        "items": rows,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "lang": lang,
        # D'où vient la liste — utile pour comprendre un classement, et pour
        # voir d'un coup d'œil qu'un serveur navigue sans son ES.
        "searchEngine": moteur,
        # L'état de la projection accompagne chaque page : une grille vide a
        # deux causes très différentes — rien de collecté, ou une projection
        # jamais rafraîchie — et le front doit pouvoir les distinguer.
        "projection": await cards_state(conn, media),
    }


@router.get("/catalog/genres")
async def genres(
    user: CurrentUser,
    conn: Conn,
    recherche: Search,
    media: str = Query(default=DEFAULT_MEDIA, max_length=16),
) -> dict[str, Any]:
    """Les genres présents dans l'univers, du plus fourni au moins fourni.

    Lus dans l'index quand il répond — une agrégation `terms`, quelques
    millisecondes — et dans la projection sinon. Jamais une liste figée dans
    le code : c'est TMDB qui décide de ses genres, et une constante finirait
    par mentir. Les libellés sont ceux du payload, donc en français.
    """
    cle = _media(media)
    depuis_es = await recherche.genres(MEDIA[cle])
    return {
        "items": depuis_es if depuis_es is not None else await genres_disponibles(conn, cle),
        "source": "es" if depuis_es is not None else "sql",
    }


@router.get("/catalog/works/{work_id}")
async def work(
    user: CurrentUser,
    conn: Conn,
    work_id: int,
    lang: str = Query(default="fr-FR", max_length=16),
    media: str = Query(default=DEFAULT_MEDIA, max_length=16),
) -> dict[str, Any]:
    detail = await fetch_work(conn, work_id, lang, _media(media))
    if detail is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"aucune fiche collectée pour {work_id} — l'œuvre est peut-être au "
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


@router.get("/catalog/works/{work_id}/sources")
async def work_sources(
    user: CurrentUser,
    conn: Conn,
    work_id: int,
    media: str = Query(default=DEFAULT_MEDIA, max_length=16),
) -> dict[str, Any]:
    """Ce que les sources tierces apportent sur cette œuvre, par source.

    Pas de 404 quand il n'y a rien : une œuvre non enrichie est un état normal
    — l'enrichissement passe après la collecte TMDB et ne couvre pas encore le
    catalogue. La réponse le dit avec une liste vide, que le front sait
    afficher ; une erreur ferait croire à une panne.

    ⚠️ `media` n'est pas facultatif au sens du résultat : sans lui, le film 557
    rendait les sources de la série 557, *Camp Lazlo*.
    """
    return await fetch_rich(conn, work_id, _media(media))


@router.post("/catalog/refresh")
async def refresh(user: CurrentUser, conn: Conn, recherche: Search) -> dict[str, Any]:
    """Recalcule la projection des vignettes depuis le brut — puis rattrape
    l'index de recherche dans la foulée.

    L'enchaînement n'est pas décoratif : la synchronisation relit les
    métadonnées de vignette DANS la projection, elle doit donc passer après
    son recalcul. Best-effort — un refresh ne doit jamais échouer parce
    qu'Elasticsearch tousse ; le bilan dit ce qui s'est passé, univers par
    univers.
    """
    total = await refresh_cards(conn)
    return {
        "projected": total,
        "search": await recherche.synchroniser_tout(conn),
        **await cards_state(conn, DEFAULT_MEDIA),
    }
