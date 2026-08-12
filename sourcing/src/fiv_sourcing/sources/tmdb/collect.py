"""Collecte d'une œuvre TMDB : la fiche, puis ses parties s'il y en a.

Une réponse HTTP = une ligne de `raw_source`. C'est l'invariant de la couche de
collecte, et c'est ce qui permet à chaque saison d'avoir sa propre fraîcheur,
son propre statut et sa propre empreinte. Le regroupement des saisons sous une
série est le travail de la dérivation, pas celui-ci.

Aucune interprétation ici non plus. Le seul champ du payload que ce module lit
est la liste des saisons — parce qu'il faut bien savoir quoi télécharger.

**Un film n'a pas de parties**, et c'est tout ce qui le distingue ici : une
requête, une ligne de brut, terminé. Le synopsis anglais qu'attend la notation
arrive dans `translations`, appendu à cet appel unique. D'où un rapport de coût
d'environ 1 à 40 avec une série, et un catalogue de films à portée là où celui
des séries se compte en jours de collecte.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import psycopg

from fiv_sourcing import store
from fiv_sourcing.http import FetchResult
from fiv_sourcing.sources.tmdb.client import TmdbClient
from fiv_sourcing.univers import FILMS, SERIES, Univers

log = logging.getLogger(__name__)

SOURCE = "tmdb"
KIND_SERIES = "tv"
KIND_SEASON = "tv_season"
KIND_MOVIE = "movie"


@dataclass(slots=True)
class CollectReport:
    tv_id: int
    status: int = 0
    requests: int = 0
    rows_written: int = 0
    seasons_seen: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.errors


async def collect_series(
    conn: psycopg.AsyncConnection,
    client: TmdbClient,
    tv_id: int,
    *,
    season_concurrency: int = 4,
) -> CollectReport:
    report = CollectReport(tv_id=tv_id)

    result = await client.series(tv_id)
    report.requests += 1
    report.status = result.status
    written = await _persist(conn, KIND_SERIES, str(tv_id), "fr-FR", result)
    report.rows_written += int(written)

    if not result.ok or result.payload is None:
        report.errors.append(result.error or f"HTTP {result.status}")
        return report

    # Le pivot d'identité naît ici, et pas ailleurs.
    #
    # Il était jusqu'au lot 12 créé paresseusement, à l'enrichissement : inutile
    # de fabriquer 228 000 lignes pour un catalogue dont la plus grande part
    # n'aura jamais une ligne de `riche_source`. Ce raisonnement est tombé le
    # jour où la notation a cessé de désigner ses œuvres par leur identifiant
    # TMDB — une série collectée doit pouvoir être notée sans être passée par
    # l'enrichissement, et l'admin n'écrit jamais dans `sourcing`.
    #
    # La règle est donc : **une œuvre existe dès que sa fiche a été
    # téléchargée**. Après le `return` ci-dessus, et pas avant : un 404 dit
    # quelque chose sur la source, pas sur l'existence d'une œuvre.
    await store.ensure_oeuvres(conn, [tv_id])

    season_numbers = [
        s["season_number"]
        for s in result.payload.get("seasons") or []
        if s.get("season_number") is not None
    ]
    report.seasons_seen = len(season_numbers)

    # Les saisons d'une même série sont indépendantes : on les tire en
    # parallèle, sous le plafond du limiteur global.
    semaphore = asyncio.Semaphore(season_concurrency)

    async def one_season(number: int, language: str) -> tuple[bool, str | None]:
        async with semaphore:
            res = await client.season(tv_id, number, language=language)
        wrote = await _persist(conn, KIND_SEASON, f"{tv_id}/s{number}", language, res)
        return wrote, None if res.ok else (res.error or f"HTTP {res.status}")

    tasks = [
        one_season(number, language)
        for number in season_numbers
        for language in client.season_languages
    ]
    for wrote, error in await asyncio.gather(*tasks):
        report.requests += 1
        report.rows_written += int(wrote)
        if error:
            report.errors.append(error)

    return report


async def collect_movie(
    conn: psycopg.AsyncConnection, client: TmdbClient, movie_id: int
) -> CollectReport:
    """Collecte un film : une requête, une ligne de brut.

    Volontairement écrite à part plutôt qu'en branche de `collect_series`. Les
    deux ne partagent que six lignes — l'appel, la persistance, le pivot — et
    les fusionner donnerait une fonction dont la moitié du corps serait sous un
    `if univers.parties`, pour une économie nulle. La collecte d'une série est
    une orchestration (saisons × langues, sémaphore, agrégation d'erreurs) ;
    celle d'un film est un appel.
    """
    report = CollectReport(tv_id=movie_id)

    result = await client.movie(movie_id)
    report.requests += 1
    report.status = result.status
    written = await _persist(conn, KIND_MOVIE, str(movie_id), "fr-FR", result)
    report.rows_written += int(written)

    if not result.ok or result.payload is None:
        report.errors.append(result.error or f"HTTP {result.status}")
        return report

    # Le pivot, à la même condition que pour une série : la fiche a été servie.
    await store.ensure_oeuvres(conn, [movie_id], univers=FILMS.cle)
    return report


COLLECTEURS = {SERIES.cle: collect_series, FILMS.cle: collect_movie}


async def collect(
    conn: psycopg.AsyncConnection, client: TmdbClient, oeuvre_id: int, univers: Univers = SERIES
) -> CollectReport:
    """Collecte une œuvre dans l'univers demandé — le point d'entrée commun de
    la ligne de commande et du rattrapage."""
    return await COLLECTEURS[univers.cle](conn, client, oeuvre_id)


# Un 401/403 ne dit rien sur l'œuvre, seulement sur notre configuration. Le
# stocker polluerait `raw_source` d'autant de lignes qu'il y a d'ids tentés le
# jour où un jeton expire. Un 404, à l'inverse, est un fait sur la source —
# « cet id a disparu de TMDB » — et se conserve.
NOT_ABOUT_THE_WORK = frozenset({401, 403})


async def _persist(
    conn: psycopg.AsyncConnection,
    kind: str,
    source_id: str,
    lang: str,
    result: FetchResult,
) -> bool:
    written = False
    if result.status not in NOT_ABOUT_THE_WORK:
        written = await store.store_raw(
            conn,
            source=SOURCE,
            kind=kind,
            source_id=source_id,
            lang=lang,
            http_status=result.status,
            payload=result.payload,
        )
    await store.mark_fetch(
        conn,
        source=SOURCE,
        kind=kind,
        source_id=source_id,
        http_status=result.status,
        changed=written,
        error=result.error,
    )
    return written
