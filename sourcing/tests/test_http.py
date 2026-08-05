from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx

from fiv_sourcing.http import HttpFetcher, RateLimiter


@pytest.fixture
async def fetcher():
    f = HttpFetcher(rate_limit=0, max_attempts=3)
    yield f
    await f.aclose()


@respx.mock
async def test_succes_direct(fetcher: HttpFetcher):
    respx.get("https://api.test/tv/1").mock(httpx.Response(200, json={"id": 1}))
    result = await fetcher.get_json("https://api.test/tv/1")
    assert result.ok
    assert result.payload == {"id": 1}
    assert result.attempts == 1


@respx.mock
async def test_429_respecte_retry_after(fetcher: HttpFetcher, monkeypatch):
    """Sur un 429, on attend ce que le serveur demande — pas le backoff."""
    attentes: list[float] = []

    async def fake_sleep(delay: float) -> None:
        attentes.append(delay)

    monkeypatch.setattr("fiv_sourcing.http.asyncio.sleep", fake_sleep)
    route = respx.get("https://api.test/tv/1")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"id": 1}),
    ]

    result = await fetcher.get_json("https://api.test/tv/1")
    assert result.ok
    assert result.attempts == 2
    assert attentes == [7.0]


@respx.mock
async def test_404_ne_retente_pas(fetcher: HttpFetcher):
    """Une série supprimée chez TMDB est un résultat, pas une erreur réseau :
    on le remonte immédiatement pour le tracer dans fetch_state."""
    route = respx.get("https://api.test/tv/404").mock(httpx.Response(404, text="Not found"))
    result = await fetcher.get_json("https://api.test/tv/404")
    assert not result.ok
    assert result.status == 404
    assert result.attempts == 1
    assert route.call_count == 1


@respx.mock
async def test_abandon_apres_max_tentatives(fetcher: HttpFetcher, monkeypatch):
    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("fiv_sourcing.http.asyncio.sleep", fake_sleep)
    route = respx.get("https://api.test/tv/1").mock(httpx.Response(503))
    result = await fetcher.get_json("https://api.test/tv/1")
    assert not result.ok
    assert result.status == 503
    assert route.call_count == 3


async def test_limiteur_espace_les_acquisitions():
    limiter = RateLimiter(rate=50)  # 20 ms entre deux créneaux
    debut = time.perf_counter()
    await asyncio.gather(*(limiter.acquire() for _ in range(5)))
    ecoule = time.perf_counter() - debut
    # 5 créneaux à 20 ms : le premier est immédiat, les 4 suivants attendent.
    assert ecoule >= 0.075


async def test_limiteur_desactive_quand_rate_nul():
    limiter = RateLimiter(rate=0)
    debut = time.perf_counter()
    await asyncio.gather(*(limiter.acquire() for _ in range(100)))
    assert time.perf_counter() - debut < 0.05
