"""L'enrichissement de bout en bout, réseau simulé.

Nécessite Postgres. Ce qu'on vérifie ici n'est pas le parsing — il a ses tests —
mais l'enchaînement : ce qui est écrit dans `raw_source`, ce qui atterrit dans
`series_source`, et surtout **par quelle voie** le raccordement s'est fait.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.enrich import build_clients, build_fetcher, enrich_series
from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

TV_ID = 1399
QID = "Q23572"
IMDB = "tt0944947"

SPARQL_TROUVE = {
    "results": {
        "bindings": [
            {
                "item": {"value": f"http://www.wikidata.org/entity/{QID}"},
                "imdb": {"value": IMDB},
                "tvmaze": {"value": "82"},
                "pays": {"value": "US"},
                "tournage": {"value": "Belfast"},
            }
        ]
    }
}
SPARQL_VIDE = {"results": {"bindings": []}}

ENTITE = {
    "entities": {
        QID: {
            "sitelinks": {
                "frwiki": {"title": "Le Trône de fer"},
                "enwiki": {"title": "Game of Thrones"},
            }
        }
    }
}

SHOW = {
    "id": 82,
    "url": "https://www.tvmaze.com/shows/82",
    "name": "Game of Thrones",
    "status": "Ended",
    "premiered": "2011-04-17",
    "network": {"name": "HBO", "country": {"code": "US"}},
    "schedule": {"days": ["Sunday"], "time": "21:00"},
    "image": {"original": "https://static.tvmaze.com/poster.jpg"},
    "externals": {"imdb": IMDB},
    "_embedded": {"episodes": [{"airdate": "2011-04-17", "summary": "<p>Ned part.</p>"}]},
}


async def _catalogue(conn) -> None:
    await load_catalog(
        conn,
        iter([{"id": TV_ID, "original_name": "Game of Thrones", "popularity": 1.0}]),
        date(2026, 8, 6),
    )


def _mock(sparql: dict) -> None:
    respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(200, json=sparql)
    )
    respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        httpx.Response(200, json=ENTITE)
    )
    for lang, titre in (("fr", "Le Trône de fer"), ("en", "Game of Thrones")):
        respx.get(url__startswith=f"https://{lang}.wikipedia.org/w/api.php").mock(
            httpx.Response(
                200,
                json={"query": {"pages": [{"title": titre, "extract": f"Intrigue en {lang}."}]}},
            )
        )
    respx.get(url__startswith="https://api.tvmaze.com/shows/82").mock(
        httpx.Response(200, json=SHOW)
    )


async def _enrichir(conn, settings: Settings):
    fetcher = build_fetcher(settings)
    async with fetcher:
        return await enrich_series(conn, build_clients(fetcher), TV_ID, languages=("fr", "en"))


@respx.mock
async def test_une_serie_raccordee_remplit_les_trois_sources(conn, settings: Settings):
    await _catalogue(conn)
    _mock(SPARQL_TROUVE)

    report = await _enrichir(conn, settings)

    assert report.qid == QID
    assert report.resolved_by == "p4983"
    assert set(report.sources) == {"wikidata", "wikipedia/fr", "wikipedia/en", "tvmaze"}
    assert not report.errors

    async with conn.cursor() as cur:
        await cur.execute(
            "select source, lang, source_id, resolved_by, content_chars, media_count "
            "from series_source order by source, lang"
        )
        assert await cur.fetchall() == [
            ("tvmaze", "", "82", "p8600", len("Ned part."), 1),
            ("wikidata", "", QID, "p4983", 0, 0),
            ("wikipedia", "en", "Game of Thrones", "sitelink", len("Intrigue en en."), 0),
            ("wikipedia", "fr", "Le Trône de fer", "sitelink", len("Intrigue en fr."), 0),
        ]


@respx.mock
async def test_le_brut_garde_une_ligne_par_reponse(conn, settings: Settings):
    """L'invariant de la couche de collecte ne change pas parce que la source
    change : une réponse HTTP, une ligne."""
    await _catalogue(conn)
    _mock(SPARQL_TROUVE)

    await _enrichir(conn, settings)

    async with conn.cursor() as cur:
        await cur.execute(
            "select source, kind, count(*) from raw_source group by 1, 2 order by 1, 2"
        )
        assert await cur.fetchall() == [
            ("tvmaze", "show", 1),
            ("wikidata", "entity", 1),
            ("wikidata", "lookup", 1),
            ("wikipedia", "article", 2),
        ]


@respx.mock
async def test_rejouer_n_ecrit_pas_de_brut_mais_rafraichit_la_derivation(conn, settings: Settings):
    """`raw_source` déduplique par empreinte ; `series_source` est remplacée.
    Les deux tables n'ont pas le même contrat, et c'est voulu."""
    await _catalogue(conn)
    _mock(SPARQL_TROUVE)

    await _enrichir(conn, settings)
    second = await _enrichir(conn, settings)

    assert second.rows_written == 0
    assert set(second.sources) == {"wikidata", "wikipedia/fr", "wikipedia/en", "tvmaze"}

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from series_source")
        assert (await cur.fetchone())[0] == 4
        await cur.execute("select count(*) from raw_source")
        assert (await cur.fetchone())[0] == 5


@respx.mock
async def test_une_serie_inconnue_de_wikidata_n_ecrit_rien(conn, settings: Settings):
    """Le cas du fond de catalogue — 0 % d'item au dixième décile. La passe doit
    se terminer proprement, pas échouer."""
    await _catalogue(conn)
    _mock(SPARQL_VIDE)

    report = await _enrichir(conn, settings)

    assert report.qid is None
    assert report.sources == []
    assert not report.errors

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from series_source")
        assert (await cur.fetchone())[0] == 0
        # La tentative est tracée : on saura qu'on a déjà regardé.
        await cur.execute("select source, kind from fetch_state")
        assert await cur.fetchall() == [("wikidata", "lookup")]


@respx.mock
async def test_l_appariement_par_titre_exige_l_imdb(conn, settings: Settings):
    """Sans item Wikidata et sans `imdb_id` collecté, la recherche par titre ne
    peut rien confirmer : on n'écrit pas plutôt que d'écrire au hasard."""
    await _catalogue(conn)
    _mock(SPARQL_VIDE)
    recherche = respx.get(url__startswith="https://api.tvmaze.com/search/shows").mock(
        httpx.Response(200, json=[{"score": 30.0, "show": {"id": 999, "externals": {}}}])
    )

    report = await _enrichir(conn, settings)

    assert report.sources == []
    assert not recherche.called, "sans imdb_id, la recherche est inutile — ne pas la lancer"
