"""Collecte d'une série TMDB : la fiche, puis chaque saison en deux langues.

Aucune interprétation ici. Le seul champ du payload que ce module lit est la
liste des saisons — parce qu'il faut bien savoir quoi télécharger ensuite.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import psycopg

from fiv_sourcing import store
from fiv_sourcing.http import FetchResult
from fiv_sourcing.sources.tmdb.client import SEASON_LANGUAGES, TmdbClient

log = logging.getLogger(__name__)

SOURCE = "tmdb"
KIND_SERIES = "tv"
KIND_SEASON = "tv_season"


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
        one_season(number, language) for number in season_numbers for language in SEASON_LANGUAGES
    ]
    for wrote, error in await asyncio.gather(*tasks):
        report.requests += 1
        report.rows_written += int(wrote)
        if error:
            report.errors.append(error)

    return report


async def _persist(
    conn: psycopg.AsyncConnection,
    kind: str,
    source_id: str,
    lang: str,
    result: FetchResult,
) -> bool:
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
