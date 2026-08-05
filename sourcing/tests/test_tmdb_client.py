from __future__ import annotations

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.client import SERIES_APPEND, TmdbClient, build_fetcher


@pytest.fixture
async def client(settings: Settings):
    fetcher = build_fetcher(settings)
    yield TmdbClient(fetcher, settings)
    await fetcher.aclose()


@respx.mock
async def test_le_token_v4_passe_en_entete(client: TmdbClient):
    """La clé ne doit pas se retrouver dans l'URL : les URL sont journalisées."""
    route = respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
        httpx.Response(200, json={"id": 1399})
    )
    await client.series(1399)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer jeton-de-test"
    assert "api_key" not in str(request.url)


@respx.mock
async def test_la_cle_v3_passe_en_parametre():
    settings = Settings(tmdb_bearer="", tmdb_api_key="cle-v3", tmdb_rate_limit=0)
    fetcher = build_fetcher(settings)
    try:
        route = respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
            httpx.Response(200, json={"id": 1399})
        )
        await TmdbClient(fetcher, settings).series(1399)
        assert route.calls.last.request.url.params["api_key"] == "cle-v3"
        assert "Authorization" not in route.calls.last.request.headers
    finally:
        await fetcher.aclose()


@respx.mock
async def test_append_to_response_contient_les_cles_de_jointure(client: TmdbClient):
    """external_ids conditionne tout l'enrichissement Wikidata/Wikipédia.
    S'il disparaît de la liste, il faut retélécharger le catalogue entier."""
    route = respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
        httpx.Response(200, json={"id": 1399})
    )
    await client.series(1399)
    appended = route.calls.last.request.url.params["append_to_response"].split(",")
    assert "external_ids" in appended
    assert "content_ratings" in appended
    assert "aggregate_credits" in appended
    # Endpoints films, demandés par erreur en V1 sur des séries.
    assert "releases" not in appended
    assert "lists" not in appended
    assert len(appended) <= 20, "TMDB plafonne append_to_response à 20 sous-requêtes"
    assert len(appended) == len(SERIES_APPEND)


@respx.mock
async def test_la_saison_est_demandee_dans_la_langue_voulue(client: TmdbClient):
    route = respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399/season/2").mock(
        httpx.Response(200, json={"season_number": 2})
    )
    await client.season(1399, 2, language="en-US")
    assert route.calls.last.request.url.params["language"] == "en-US"
