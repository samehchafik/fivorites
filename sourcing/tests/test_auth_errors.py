"""Ce qui mérite d'être conservé dans `raw_source`, et ce qui ne le mérite pas.

La distinction : le brut décrit la source, pas notre configuration. Un jeton
invalide n'est pas un fait sur une série.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher
from fiv_sourcing.sources.tmdb.collect import collect_series

pytestmark = pytest.mark.integration

REFUS = {
    "status_code": 7,
    "status_message": "Invalid API key: You must be granted a valid key.",
    "success": False,
}


@respx.mock
async def test_un_401_ne_pollue_pas_le_brut(conn, settings: Settings):
    """Sinon un jeton expiré écrirait autant de lignes qu'il y a d'ids tentés."""
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
        httpx.Response(401, json=REFUS)
    )
    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await collect_series(conn, TmdbClient(fetcher, settings), 1399)

    assert not report.ok
    assert report.status == 401
    assert report.rows_written == 0

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from raw_source")
        assert (await cur.fetchone())[0] == 0


@respx.mock
async def test_un_401_reste_visible_dans_fetch_state(conn, settings: Settings):
    """On ne conserve pas la réponse, mais on garde la trace de la tentative :
    c'est ce qui permettra de rejouer les ids ratés une fois le jeton corrigé."""
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
        httpx.Response(401, json=REFUS)
    )
    fetcher = build_fetcher(settings)
    async with fetcher:
        await collect_series(conn, TmdbClient(fetcher, settings), 1399)

    async with conn.cursor() as cur:
        await cur.execute("select last_status, last_success_at from fetch_state")
        last_status, last_success = await cur.fetchone()

    assert last_status == 401
    assert last_success is None
