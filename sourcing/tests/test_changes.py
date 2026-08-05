"""Détection des modifications côté TMDB.

Le point sensible : une marque en base plutôt qu'une collecte immédiate. Si le
relevé des modifications échoue à mi-parcours, ce qu'il a déjà marqué reste
acquis et sera repris au prochain `backfill`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.backfill import backfill, pending_ids
from fiv_sourcing.sources.tmdb.changes import fetch_changed_ids, mark_changed, refresh_changes
from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher
from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

JOUR = date(2026, 8, 5)
CHANGES = "https://api.themoviedb.org/3/tv/changes"


@pytest.fixture
async def client(settings: Settings):
    fetcher = build_fetcher(settings)
    yield TmdbClient(fetcher, settings)
    await fetcher.aclose()


async def _catalogue(conn, ids: list[int]) -> None:
    await load_catalog(
        conn,
        iter([{"id": i, "original_name": f"S{i}", "popularity": 1.0} for i in ids]),
        JOUR,
    )


def _mock_serie(tv_id: int) -> None:
    respx.get(url__startswith=f"https://api.themoviedb.org/3/tv/{tv_id}/season/").mock(
        httpx.Response(200, json={"season_number": 1, "episodes": []})
    )
    respx.get(url__startswith=f"https://api.themoviedb.org/3/tv/{tv_id}").mock(
        httpx.Response(200, json={"id": tv_id, "seasons": [{"season_number": 1}]})
    )


@respx.mock
async def test_la_pagination_est_suivie_jusqu_au_bout(client: TmdbClient):
    respx.get(url__startswith=CHANGES).side_effect = [
        httpx.Response(200, json={"results": [{"id": 1}, {"id": 2}], "total_pages": 3}),
        httpx.Response(200, json={"results": [{"id": 3}], "total_pages": 3}),
        httpx.Response(200, json={"results": [{"id": 4}], "total_pages": 3}),
    ]

    ids, pages, tronque = await fetch_changed_ids(client, JOUR - timedelta(days=1), JOUR)

    assert ids == {1, 2, 3, 4}
    assert pages == 3
    assert not tronque


@respx.mock
async def test_une_page_en_erreur_conserve_ce_qui_precede(client: TmdbClient):
    """Mieux vaut marquer 200 séries sur 300 que zéro."""
    respx.get(url__startswith=CHANGES).side_effect = [
        httpx.Response(200, json={"results": [{"id": 1}], "total_pages": 3}),
        httpx.Response(404),
    ]

    ids, _, _ = await fetch_changed_ids(client, JOUR - timedelta(days=1), JOUR)

    assert ids == {1}


async def test_seules_les_series_connues_sont_marquees(conn):
    """Une série créée aujourd'hui apparaît dans /tv/changes avant d'entrer
    dans l'export quotidien : on ne l'invente pas, l'export la rattrapera."""
    await _catalogue(conn, [1, 2])

    marquees = await mark_changed(conn, {1, 2, 999})

    assert marquees == 2


@respx.mock
async def test_une_serie_modifiee_est_reprise_par_le_backfill(conn, settings: Settings):
    """Le cœur du mécanisme : la marque devient une recollecte."""
    await _catalogue(conn, [1399])
    _mock_serie(1399)

    fetcher = build_fetcher(settings)
    async with fetcher:
        client = TmdbClient(fetcher, settings)
        await backfill(conn, client, [1399])
        assert await pending_ids(conn) == [], "collectée, donc plus rien à faire"

        # TMDB signale une modification postérieure à notre collecte.
        await mark_changed(conn, {1399}, at=datetime.now(UTC) + timedelta(minutes=1))

    assert await pending_ids(conn) == [1399]


@respx.mock
async def test_une_modification_anterieure_a_la_collecte_ne_declenche_rien(
    conn, settings: Settings
):
    """C'est la comparaison des dates qui compte, pas la simple présence d'une
    marque — sinon une série resterait éternellement à recollecter."""
    await _catalogue(conn, [1399])
    _mock_serie(1399)

    await mark_changed(conn, {1399}, at=datetime.now(UTC) - timedelta(days=2))

    fetcher = build_fetcher(settings)
    async with fetcher:
        await backfill(conn, TmdbClient(fetcher, settings), [1399])

    assert await pending_ids(conn) == []


@respx.mock
async def test_le_bilan_distingue_marquees_et_inconnues(conn, client: TmdbClient):
    await _catalogue(conn, [1, 2])
    respx.get(url__startswith=CHANGES).mock(
        httpx.Response(200, json={"results": [{"id": 1}, {"id": 999}], "total_pages": 1})
    )

    report = await refresh_changes(conn, client, days=1, today=JOUR)

    assert report.ids_seen == 2
    assert report.marked == 1
    assert report.unknown == 1
    assert (report.start, report.end) == (JOUR - timedelta(days=1), JOUR)


@respx.mock
async def test_la_fenetre_est_plafonnee_a_quatorze_jours(conn, client: TmdbClient):
    """Au-delà, TMDB tronque silencieusement — autant demander ce qu'il peut
    donner plutôt que de croire à une réponse complète."""
    await _catalogue(conn, [1])
    route = respx.get(url__startswith=CHANGES).mock(
        httpx.Response(200, json={"results": [], "total_pages": 1})
    )

    report = await refresh_changes(conn, client, days=90, today=JOUR)

    assert (JOUR - report.start).days == 14
    assert route.calls.last.request.url.params["start_date"] == str(JOUR - timedelta(days=14))
