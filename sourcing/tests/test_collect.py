"""Le critère d'acceptation du lot 1, vérifié de bout en bout.

Nécessite Postgres (`make db-create`). TMDB est simulé : ces tests ne sortent pas
sur le réseau.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher
from fiv_sourcing.sources.tmdb.collect import collect_series

pytestmark = pytest.mark.integration

SERIE = {
    "id": 1399,
    "name": "Le Trône de fer",
    "seasons": [{"season_number": 1}, {"season_number": 2}],
    "external_ids": {"imdb_id": "tt0944947", "wikidata_id": "Q23572"},
}


def _mock_tmdb() -> None:
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399/season/").mock(
        httpx.Response(200, json={"season_number": 1, "episodes": []})
    )
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
        httpx.Response(200, json=SERIE)
    )


@respx.mock
async def test_collecte_ecrit_la_serie_et_ses_saisons(conn, settings: Settings):
    _mock_tmdb()
    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await collect_series(conn, TmdbClient(fetcher, settings), 1399)

    assert report.ok
    assert report.seasons_seen == 2
    # 1 fiche série + 2 saisons × 2 langues
    assert report.requests == 5
    assert report.rows_written == 5

    async with conn.cursor() as cur:
        await cur.execute("select kind, count(*) from raw_source group by kind order by kind")
        assert await cur.fetchall() == [("tv", 1), ("tv_season", 4)]


@respx.mock
async def test_rejouer_a_l_identique_n_ecrit_rien(conn, settings: Settings):
    """`raw_source` ne doit pas grossir quand la source n'a pas bougé —
    c'est ce qui rend un rafraîchissement quotidien du catalogue soutenable."""
    _mock_tmdb()
    fetcher = build_fetcher(settings)
    async with fetcher:
        client = TmdbClient(fetcher, settings)
        first = await collect_series(conn, client, 1399)
        second = await collect_series(conn, client, 1399)

    assert first.rows_written == 5
    assert second.rows_written == 0
    assert second.requests == 5  # on a bien redemandé, on n'a juste rien réécrit

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from raw_source")
        assert (await cur.fetchone())[0] == 5


@respx.mock
async def test_le_deuxieme_passage_met_a_jour_la_fraicheur(conn, settings: Settings):
    """Rien de nouveau à stocker, mais on sait quand même qu'on a regardé."""
    _mock_tmdb()
    fetcher = build_fetcher(settings)
    async with fetcher:
        client = TmdbClient(fetcher, settings)
        await collect_series(conn, client, 1399)
        async with conn.cursor() as cur:
            await cur.execute(
                "select last_fetched_at, last_changed_at from fetch_state "
                "where kind = 'tv' and source_id = '1399'"
            )
            fetched_1, changed_1 = await cur.fetchone()

        await collect_series(conn, client, 1399)
        async with conn.cursor() as cur:
            await cur.execute(
                "select last_fetched_at, last_changed_at, attempts from fetch_state "
                "where kind = 'tv' and source_id = '1399'"
            )
            fetched_2, changed_2, attempts = await cur.fetchone()

    assert fetched_2 > fetched_1, "last_fetched_at doit avancer à chaque passage"
    assert changed_2 == changed_1, "last_changed_at ne bouge que si le contenu a changé"
    assert attempts == 2


@respx.mock
async def test_une_serie_supprimee_est_tracee(conn, settings: Settings):
    """Un 404 se conserve : c'est l'information « cet id a disparu de TMDB »,
    que la V1 était incapable de détecter."""
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/999999").mock(
        httpx.Response(
            404, json={"status_message": "The resource you requested could not be found"}
        )
    )
    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await collect_series(conn, TmdbClient(fetcher, settings), 999999)

    assert not report.ok
    assert report.status == 404
    assert report.seasons_seen == 0

    async with conn.cursor() as cur:
        await cur.execute("select http_status, payload from raw_source")
        status, payload = await cur.fetchone()
        assert (status, payload) == (404, None)
        await cur.execute("select last_status, last_success_at from fetch_state")
        last_status, last_success = await cur.fetchone()
        assert last_status == 404
        assert last_success is None
