"""L'export quotidien : nommage, tolérance aux lignes cassées, repli de date."""

from __future__ import annotations

import gzip
import json
from datetime import date

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.client import build_public_fetcher
from fiv_sourcing.sources.tmdb.export import (
    ExportUnavailable,
    download_export,
    export_url,
    parse_export,
)

SERIES = [
    {"id": 1399, "original_name": "Game of Thrones", "popularity": 412.5, "adult": False},
    {"id": 1396, "original_name": "Breaking Bad", "popularity": 380.1, "adult": False},
]


def _gz(records: list[dict], *, extra: bytes = b"") -> bytes:
    body = b"\n".join(json.dumps(r).encode() for r in records) + b"\n" + extra
    return gzip.compress(body)


@pytest.fixture
async def fetcher(settings: Settings):
    f = build_public_fetcher(settings)
    yield f
    await f.aclose()


def test_le_nom_de_fichier_suit_le_format_de_tmdb():
    """MM_DD_YYYY, pas ISO — se tromper donne un 403 silencieux."""
    assert export_url(date(2026, 8, 5)).endswith("tv_series_ids_08_05_2026.json.gz")
    assert export_url(date(2026, 12, 31)).endswith("tv_series_ids_12_31_2026.json.gz")


def test_le_fichier_est_du_json_par_lignes():
    assert [r["id"] for r in parse_export(_gz(SERIES))] == [1399, 1396]


def test_une_ligne_illisible_ne_perd_pas_le_reste():
    """Un export tronqué reste plus utile qu'aucun catalogue."""
    records = list(parse_export(_gz(SERIES, extra=b'{"id": 42, "original_na\n')))
    assert [r["id"] for r in records] == [1399, 1396]


@respx.mock
async def test_repli_sur_le_jour_precedent(fetcher):
    """L'export du jour n'est publié qu'en milieu de matinée UTC : demander
    trop tôt ne doit pas faire échouer la commande."""
    respx.get(export_url(date(2026, 8, 5))).mock(httpx.Response(403))
    respx.get(export_url(date(2026, 8, 4))).mock(httpx.Response(200, content=_gz(SERIES)))

    exported_on, url, blob = await download_export(fetcher, start=date(2026, 8, 5))

    assert exported_on == date(2026, 8, 4), "la date renvoyée est celle du fichier obtenu"
    assert url == export_url(date(2026, 8, 4))
    assert [r["id"] for r in parse_export(blob)] == [1399, 1396]


@respx.mock
async def test_une_date_explicite_ne_declenche_pas_de_repli(fetcher):
    """Demander un jour précis est un ordre : renvoyer l'export de la veille
    sous une date non demandée serait un mensonge silencieux."""
    respx.get(export_url(date(2026, 8, 5))).mock(httpx.Response(404))
    veille = respx.get(export_url(date(2026, 8, 4))).mock(httpx.Response(200, content=_gz(SERIES)))

    with pytest.raises(ExportUnavailable, match="404"):
        await download_export(fetcher, start=date(2026, 8, 5), strict=True)

    assert veille.call_count == 0


@respx.mock
async def test_abandon_si_aucun_export_sur_la_fenetre(fetcher):
    route = respx.get(url__startswith="http://files.tmdb.org/p/exports/").mock(httpx.Response(403))
    with pytest.raises(ExportUnavailable, match="aucun export"):
        await download_export(fetcher, start=date(2026, 8, 5), fallback_days=2)

    assert route.call_count == 3, "le jour demandé plus deux jours de repli"
