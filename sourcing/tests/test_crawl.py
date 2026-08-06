"""Le flux 2 : les séries dans Wikidata mais pas dans TMDB.

Réseau simulé, Postgres réel. Ce qu'on fige : l'œuvre naît par QID sans aucun
ancrage TMDB, le brut est conservé (R1), la reprise saute le déjà-vu, et un
crawl qui retombe sur un QID déjà attaché réutilise l'œuvre au lieu d'en créer
une seconde.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.crawl import CrawlReport, crawl_wikidata, deja_regardes, sweep
from fiv_sourcing.enrich import build_clients, build_fetcher
from fiv_sourcing.sources import wikidata

pytestmark = pytest.mark.integration


def _page_sweep(*items: tuple[str, str]) -> dict:
    return {
        "results": {
            "bindings": [
                {
                    "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                    "itemLabel": {"value": titre},
                }
                for qid, titre in items
            ]
        }
    }


def _lookup_qid(qid: str) -> dict:
    return {
        "results": {
            "bindings": [
                {
                    "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                    "pays": {"value": "SA"},
                    "langues": {"value": "ar"},
                }
            ]
        }
    }


def _mock(qid: str, titre: str) -> None:
    respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(200, json=_lookup_qid(qid))
    )
    respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        httpx.Response(
            200,
            json={"entities": {qid: {"sitelinks": {"arwiki": {"title": titre}}}}},
        )
    )
    respx.get(url__startswith="https://ar.wikipedia.org/w/api.php").mock(
        httpx.Response(
            200, json={"query": {"pages": [{"title": titre, "extract": "نص المقال الكامل."}]}}
        )
    )


async def _lancer(conn, settings: Settings, items):
    fetcher = build_fetcher(settings)
    async with fetcher:
        return await crawl_wikidata(
            conn, build_clients(fetcher), items, languages=("ar",), report=CrawlReport()
        )


@respx.mock
async def test_le_sweep_pagine_jusqu_a_epuisement(settings: Settings):
    pages = [
        _page_sweep(("Q1", "Un"), ("Q2", "Deux")),
        _page_sweep(("Q3", "Trois")),
    ]
    route = respx.get(url__startswith="https://query.wikidata.org/sparql")
    route.side_effect = [httpx.Response(200, json=p) for p in pages]

    import fiv_sourcing.crawl as crawl_module

    ancien = crawl_module.PAGE
    crawl_module.PAGE = 2
    try:
        report = CrawlReport()
        fetcher = build_fetcher(settings)
        async with fetcher:
            items = await sweep(build_clients(fetcher), report)
    finally:
        crawl_module.PAGE = ancien

    assert [i["qid"] for i in items] == ["Q1", "Q2", "Q3"]
    assert report.swept == 3
    assert route.call_count == 2, "la page incomplète arrête la pagination"


@respx.mock
async def test_une_oeuvre_nait_par_qid_sans_ancrage_tmdb(conn, settings: Settings):
    _mock("Q777", "مسلسل خليجي")

    report = await _lancer(conn, settings, [{"qid": "Q777", "titre": "مسلسل خليجي"}])

    assert report.done == 1
    assert report.enriched == 1

    async with conn.cursor() as cur:
        await cur.execute("select id_tmdb, wikidata_qid, titre from oeuvre")
        assert await cur.fetchall() == [(None, "Q777", "مسلسل خليجي")]

        await cur.execute(
            "select source, lang, id_tmdb, raw_source_id, resolved_by, content_chars "
            "from riche_source order by source, lang"
        )
        lignes = await cur.fetchall()
    assert ("wikidata", "", None, None, "sweep", 0) in lignes
    assert ("wikipedia", "ar", None, None, "sitelink", len("نص المقال الكامل.")) in lignes


@respx.mock
async def test_le_brut_du_crawl_est_conserve_par_qid(conn, settings: Settings):
    """R1 vaut pour les deux flux : lookup et articles entrent dans raw_source,
    keyés par QID — l'espace de noms du flux 1 (ids TMDB numériques) n'est
    jamais croisé."""
    _mock("Q777", "مسلسل")

    await _lancer(conn, settings, [{"qid": "Q777", "titre": "مسلسل"}])

    async with conn.cursor() as cur:
        await cur.execute("select source, kind, source_id from raw_source order by source, kind")
        assert await cur.fetchall() == [
            ("wikidata", "entity", "Q777"),
            ("wikidata", "lookup", "Q777"),
            ("wikipedia", "article", "مسلسل"),
        ]


@respx.mock
async def test_la_reprise_saute_le_deja_vu(conn, settings: Settings):
    _mock("Q777", "مسلسل")
    await _lancer(conn, settings, [{"qid": "Q777", "titre": "مسلسل"}])

    vus = await deja_regardes(conn, ["Q777", "Q888"])

    assert vus == {"Q777"}


@respx.mock
async def test_un_qid_deja_attache_reutilise_l_oeuvre(conn, settings: Settings):
    """La réconciliation dans le bon sens : si le flux 1 a déjà attaché ce QID
    à une œuvre, le crawl la complète au lieu d'en créer une seconde."""
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into oeuvre (univers, wikidata_qid, titre) "
            "values ('series', 'Q777', 'déjà là') returning id"
        )
        existante = (await cur.fetchone())[0]
    _mock("Q777", "مسلسل")

    await _lancer(conn, settings, [{"qid": "Q777", "titre": "مسلسل"}])

    async with conn.cursor() as cur:
        await cur.execute("select count(*), max(id) from oeuvre")
        assert await cur.fetchone() == (1, existante)


def test_le_sweep_ignore_les_labels_absents():
    """Le service de labels renvoie le QID quand aucun libellé n'existe : ce
    n'est pas un titre."""
    payload = _page_sweep(("Q42", "Q42"))
    assert wikidata.lire_sweep(payload) == [
        {"qid": "Q42", "titre": None, "imdb": None, "tvmaze": None}
    ]
