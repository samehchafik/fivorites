"""Les compteurs qui répondent à « quel débit TMDB tolère-t-il ? ».

TMDB a supprimé sa limite dure en 2019 et le plafond qui subsiste n'est pas
documenté. Plutôt que de régler le débit sur une valeur trouvée dans un forum,
on compte les 429 d'une passe réelle.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fiv_sourcing.http import HttpFetcher


@pytest.fixture
async def fetcher(monkeypatch):
    async def sans_attente(delay: float) -> None:
        return None

    monkeypatch.setattr("fiv_sourcing.http.asyncio.sleep", sans_attente)
    f = HttpFetcher(rate_limit=0, max_attempts=3)
    yield f
    await f.aclose()


@respx.mock
async def test_une_passe_sans_bridage_ne_compte_aucun_429(fetcher: HttpFetcher):
    respx.get("https://api.test/a").mock(httpx.Response(200, json={}))
    await fetcher.get_json("https://api.test/a")

    assert fetcher.stats.requests == 1
    assert fetcher.stats.rate_limited == 0
    assert fetcher.stats.retries == 0
    assert fetcher.stats.rate_limited_ratio == 0.0


@respx.mock
async def test_les_429_sont_comptes_et_le_retry_after_trace(fetcher: HttpFetcher):
    respx.get("https://api.test/a").side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={}),
    ]
    result = await fetcher.get_json("https://api.test/a")

    assert result.ok
    assert fetcher.stats.requests == 2, "la reprise compte comme une requête émise"
    assert fetcher.stats.retries == 1
    assert fetcher.stats.rate_limited == 1
    assert fetcher.stats.honoured_retry_after == 1
    assert fetcher.stats.rate_limited_ratio == 0.5


@respx.mock
async def test_les_erreurs_reseau_sont_distinguees_du_bridage(fetcher: HttpFetcher):
    """Un plafond dépassé et une coupure réseau appellent des réactions
    opposées — baisser le débit, ou justement pas."""
    respx.get("https://api.test/a").mock(side_effect=httpx.ConnectError("coupure"))
    await fetcher.get_json("https://api.test/a")

    assert fetcher.stats.transport_errors == 3
    assert fetcher.stats.rate_limited == 0


@respx.mock
async def test_les_compteurs_couvrent_aussi_le_telechargement_de_fichiers(fetcher: HttpFetcher):
    respx.get("http://files.test/export.gz").mock(httpx.Response(200, content=b"x"))
    await fetcher.get_bytes("http://files.test/export.gz")

    assert fetcher.stats.requests == 1
