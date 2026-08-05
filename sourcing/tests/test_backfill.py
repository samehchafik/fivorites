"""La collecte de masse : sélection, reprise, arrêt propre.

Le principe que ces tests protègent : **aucun filtre à l'acquisition**. Le
`backfill` prend tout le catalogue, quelle que soit la popularité, parce que
`popularity` mesure l'attention des utilisateurs de TMDB et pas l'audience
réelle — s'en servir pour trier écarterait les catalogues arabe et turc.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.backfill import backfill, pending_ids
from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher
from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

JOUR = date(2026, 8, 5)


async def _catalogue(conn, entrees: list[tuple[int, str, float]]) -> None:
    await load_catalog(
        conn,
        iter(
            [
                {"id": i, "original_name": nom, "popularity": pop, "adult": False}
                for i, nom, pop in entrees
            ]
        ),
        JOUR,
    )


def _mock_serie(tv_id: int, seasons: int = 1) -> None:
    respx.get(url__startswith=f"https://api.themoviedb.org/3/tv/{tv_id}/season/").mock(
        httpx.Response(200, json={"season_number": 1, "episodes": []})
    )
    respx.get(url__startswith=f"https://api.themoviedb.org/3/tv/{tv_id}").mock(
        httpx.Response(
            200,
            json={
                "id": tv_id,
                "name": f"Série {tv_id}",
                "seasons": [{"season_number": n} for n in range(1, seasons + 1)],
            },
        )
    )


async def test_toutes_les_series_sont_selectionnees_quelle_que_soit_la_popularite(conn):
    """Une série à 0,1 de popularité est sélectionnée comme une à 400. C'est le
    cœur de la décision : l'utilisateur tranchera, pas l'acquisition."""
    await _catalogue(conn, [(1, "Blockbuster", 400.0), (2, "باب الحارة", 0.1)])

    assert sorted(await pending_ids(conn)) == [1, 2]


async def test_le_tri_par_defaut_est_neutre(conn):
    """Trier par popularité serait un jugement implicite ; l'id ne dit rien."""
    await _catalogue(conn, [(7, "Peu vue", 0.1), (3, "Très vue", 400.0)])

    assert await pending_ids(conn) == [3, 7]
    assert await pending_ids(conn, order="popularity") == [3, 7]


async def test_le_tri_par_popularite_reste_disponible(conn):
    await _catalogue(conn, [(3, "Peu vue", 0.1), (7, "Très vue", 400.0)])

    assert await pending_ids(conn, order="id") == [3, 7]
    assert await pending_ids(conn, order="popularity") == [7, 3]


async def test_un_tri_inconnu_est_refuse(conn):
    """Le nom du tri est interpolé dans le SQL : il doit être clos."""
    with pytest.raises(ValueError, match="tri inconnu"):
        await pending_ids(conn, order="id; drop table raw_source")


@respx.mock
async def test_une_serie_deja_collectee_n_est_pas_reprise(conn, settings: Settings):
    """C'est ce qui rend la passe reprenable : relancer après interruption ne
    recommence pas les 100 000 séries déjà faites."""
    await _catalogue(conn, [(1399, "Game of Thrones", 400.0), (1396, "Breaking Bad", 300.0)])
    _mock_serie(1399)

    fetcher = build_fetcher(settings)
    async with fetcher:
        await backfill(conn, TmdbClient(fetcher, settings), [1399])

    assert await pending_ids(conn) == [1396]


@respx.mock
async def test_refresh_after_reprend_les_series_anciennes(conn, settings: Settings):
    await _catalogue(conn, [(1399, "Game of Thrones", 400.0)])
    _mock_serie(1399)

    fetcher = build_fetcher(settings)
    async with fetcher:
        await backfill(conn, TmdbClient(fetcher, settings), [1399])

    assert await pending_ids(conn) == []
    assert await pending_ids(conn, refresh_after=0) == [1399]


@respx.mock
async def test_une_serie_en_echec_ne_tue_pas_la_passe(conn, settings: Settings):
    """Sur 228 000 séries, une réponse aberrante ne doit pas coûter la passe."""
    await _catalogue(conn, [(1, "ok", 1.0), (2, "cassée", 1.0), (3, "ok", 1.0)])
    _mock_serie(1)
    _mock_serie(3)
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/2").mock(httpx.Response(500))

    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await backfill(conn, TmdbClient(fetcher, settings), [1, 2, 3], concurrency=2)

    assert report.done == 3
    assert report.ok == 2
    assert report.failed == 1
    assert not report.interrupted


@respx.mock
async def test_l_arret_demande_stoppe_sans_perdre_l_etat(conn, settings: Settings):
    """Une passe de trente heures doit pouvoir être interrompue : ce qui est
    collecté est acquis, le reste sera repris."""
    await _catalogue(conn, [(i, f"S{i}", 1.0) for i in range(1, 6)])
    for i in range(1, 6):
        _mock_serie(i)

    stop = asyncio.Event()
    stop.set()  # arrêt demandé avant même le démarrage

    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await backfill(
            conn, TmdbClient(fetcher, settings), [1, 2, 3, 4, 5], concurrency=1, stop=stop
        )

    assert report.done == 0
    assert report.interrupted
    assert len(await pending_ids(conn)) == 5, "rien n'a été consommé, tout reste à faire"
