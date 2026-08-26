"""Le crawler sur l'univers livres — le flux principal des livres.

Réseau simulé, Postgres réel. Ce qu'on fige : l'œuvre naît par QID dans
l'univers `livres` (disjoint des séries), le brut se range sous
`lookup_book`, l'OLID remonte sur le pivot, Open Library entre dans
`riche_source` avec le résumé d'éditions au format canonique — et la voie de
repli par titre fonctionne quand Wikidata ne porte pas P648.
"""

from __future__ import annotations

import re

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.crawl import CrawlReport, crawl_wikidata, deja_regardes
from fiv_sourcing.enrich import build_clients, build_fetcher
from fiv_sourcing.sources import openlibrary, wikidata
from fiv_sourcing.univers import LIVRES

pytestmark = pytest.mark.integration


def _lookup_livre(qid: str, olid: str | None = None) -> dict:
    binding = {
        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "auteurs": {"value": "Q5878~Gabriel García Márquez"},
        "langues": {"value": "es"},
        "pays": {"value": "CO"},
        "annee": {"value": "1967"},
    }
    if olid:
        binding["olid"] = {"value": olid}
    return {"results": {"bindings": [binding]}}


def _work(olid: str) -> dict:
    return {
        "key": f"/works/{olid}",
        "title": "Cien años de soledad",
        "description": "La saga des Buendía à Macondo.",
        # -1 est le marqueur « couverture retirée » d'Open Library.
        "covers": [283860, -1, 1008523],
    }


def _editions() -> dict:
    return {
        "size": 3,
        "entries": [
            {"languages": [{"key": "/languages/spa"}], "isbn_13": ["9780307474728"]},
            {"languages": [{"key": "/languages/fre"}], "isbn_13": ["9782020238113"]},
            {},  # l'édition sans langue taguée, mesurée à 13-18 % du réel
        ],
    }


def _mock(qid: str, olid: str | None) -> None:
    respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(200, json=_lookup_livre(qid, olid))
    )
    respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        httpx.Response(
            200,
            json={"entities": {qid: {"sitelinks": {"frwiki": {"title": "Cent ans de solitude"}}}}},
        )
    )
    respx.get(url__startswith="https://fr.wikipedia.org/w/api.php").mock(
        httpx.Response(
            200,
            json={
                "query": {
                    "pages": [{"title": "Cent ans de solitude", "extract": "Le roman de Macondo."}]
                }
            },
        )
    )
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        httpx.Response(
            200,
            json={"docs": [{"key": "/works/OL27258W", "title": "Cien años de soledad"}]},
        )
    )
    respx.get(url__startswith="https://openlibrary.org/works/OL27258W/editions.json").mock(
        httpx.Response(200, json=_editions())
    )
    respx.get(url__startswith="https://openlibrary.org/works/OL27258W.json").mock(
        httpx.Response(200, json=_work("OL27258W"))
    )


async def _lancer(conn, settings: Settings, items):
    fetcher = build_fetcher(settings)
    async with fetcher:
        return await crawl_wikidata(
            conn,
            build_clients(fetcher),
            items,
            univers=LIVRES,
            languages=("fr",),
            report=CrawlReport(),
        )


@respx.mock
async def test_un_livre_nait_par_qid_dans_son_univers(conn, settings: Settings):
    _mock("Q189378", "OL27258W")

    report = await _lancer(
        conn, settings, [{"qid": "Q189378", "titre": "Cien años de soledad", "olid": "OL27258W"}]
    )

    assert report.done == 1
    assert report.enriched == 1

    async with conn.cursor() as cur:
        await cur.execute(
            "select univers, id_tmdb, wikidata_qid, id_openlibrary, titre from oeuvre"
        )
        assert await cur.fetchall() == [
            ("livres", None, "Q189378", "OL27258W", "Cien años de soledad")
        ]

        await cur.execute(
            "select source, lang, resolved_by from riche_source order by source, lang"
        )
        lignes = await cur.fetchall()
    assert ("openlibrary", "", "p648") in lignes
    assert ("wikidata", "", "sweep") in lignes
    assert ("wikipedia", "fr", "sitelink") in lignes

    async with conn.cursor() as cur:
        await cur.execute("select media from riche_source where source = 'openlibrary'")
        media = (await cur.fetchone())[0]
    assert media == [
        {"type": "poster", "url": "https://covers.openlibrary.org/b/id/283860-L.jpg"},
        {"type": "poster", "url": "https://covers.openlibrary.org/b/id/1008523-L.jpg"},
    ], "les couvertures entrent en media, l'id retiré (-1) est écarté"


@respx.mock
async def test_les_editions_entrent_au_format_canonique(conn, settings: Settings):
    _mock("Q189378", "OL27258W")

    await _lancer(conn, settings, [{"qid": "Q189378", "titre": "Cien años", "olid": "OL27258W"}])

    async with conn.cursor() as cur:
        await cur.execute("select facts from riche_source where source = 'openlibrary'")
        facts = (await cur.fetchone())[0]
    assert facts["editions"]["total"] == 3
    assert facts["editions"]["sans_langue"] == 1
    assert {e["langue"] for e in facts["editions"]["par_langue"]} == {"es", "fr"}
    assert facts["ids"]["openlibrary"] == "OL27258W"


@respx.mock
async def test_le_brut_du_livre_se_range_sous_lookup_book(conn, settings: Settings):
    """R1, et la disjonction des univers : le lookup d'un livre ne partage ni
    le `kind` ni l'état de reprise des séries — Q123 livre et Q123 série ne
    se volent pas leur passage."""
    _mock("Q189378", "OL27258W")

    await _lancer(conn, settings, [{"qid": "Q189378", "titre": "Cien años", "olid": "OL27258W"}])

    async with conn.cursor() as cur:
        await cur.execute("select source, kind, source_id from raw_source")
        assert await cur.fetchall() == [("wikidata", "lookup_book", "Q189378")]

    assert await deja_regardes(conn, ["Q189378"], kind=LIVRES.lookup_kind) == {"Q189378"}
    assert await deja_regardes(conn, ["Q189378"]) == set()


@respx.mock
async def test_sans_p648_la_recherche_par_titre_rattrape(conn, settings: Settings):
    """La voie qui compte pour l'arabe : 60 % du corpus s'apparie par titre
    quand Wikidata ne porte l'OLID qu'à 23 % (doc/etude-sources-livres.md)."""
    _mock("Q189378", olid=None)

    await _lancer(conn, settings, [{"qid": "Q189378", "titre": "Cien años de soledad"}])

    async with conn.cursor() as cur:
        await cur.execute("select id_openlibrary from oeuvre")
        assert await cur.fetchone() == ("OL27258W",)
        await cur.execute("select resolved_by from riche_source where source = 'openlibrary'")
        assert await cur.fetchone() == ("titre+auteur",)


def test_le_sweep_livres_lit_l_olid_et_la_notoriete():
    payload = {
        "results": {
            "bindings": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q189378"},
                    "itemLabel": {"value": "Cien años de soledad"},
                    "olid": {"value": "OL27258W"},
                    "sitelinks": {"value": "112"},
                },
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q42"},
                    "itemLabel": {"value": "Q42"},
                    "sitelinks": {"value": "9"},
                },
            ]
        }
    }
    assert wikidata.lire_sweep_livres(payload) == [
        {"qid": "Q189378", "titre": "Cien años de soledad", "olid": "OL27258W", "sitelinks": 112},
        {"qid": "Q42", "titre": None, "olid": None, "sitelinks": 9},
    ]


def test_un_work_fusionne_se_suit_une_fois():
    payload = {"type": {"key": "/type/redirect"}, "location": "/works/OL999W"}
    assert openlibrary.redirection(payload) == "OL999W"
    assert openlibrary.redirection(_work("OL27258W")) is None


def test_la_recherche_saute_les_editions_orphelines():
    """La recherche Open Library renvoie parfois une clé `/works/OL…M` — une
    édition orpheline montée dans l'index (constaté : « Nahj al-Balagha »).
    Ce n'est pas un work : on prend le candidat suivant."""
    payload = {
        "docs": [
            {"key": "/works/OL19816124M", "title": "NAHJ AL-BALAGHA"},
            {"key": "/works/OL1605091W", "title": "étude sur Nahj al-Balâgha"},
        ]
    }
    assert openlibrary.lire_recherche(payload) == "OL1605091W"
    assert openlibrary.lire_recherche({"docs": [{"key": "/works/OL1M"}]}) is None


def test_l_edition_p648_remonte_a_son_work():
    assert openlibrary.work_de_l_edition({"works": [{"key": "/works/OL27258W"}]}) == "OL27258W"
    assert openlibrary.work_de_l_edition({"title": "orpheline"}) is None


def test_aucune_requete_sparql_ne_porte_de_pourcent_libre():
    """Les requêtes sont assemblées par formatage `%` de Python : un signe
    pour cent isolé — dans un commentaire, typiquement — y devient une
    spécification de format et fait échouer la collecte entière sur
    « not enough arguments for format string ». Constaté le 2026-08-22 en
    ajoutant les genres ; le message ne dit pas où chercher, d'où ce test.
    """
    from fiv_sourcing.sources import wikidata as w

    motifs = {
        "LOOKUP": w.LOOKUP,
        "LOOKUP_LOT": w.LOOKUP_LOT,
        "LOOKUP_QID": w.LOOKUP_QID,
        "LOOKUP_QID_LIVRE": w.LOOKUP_QID_LIVRE,
        "SWEEP": w.SWEEP,
        "SWEEP_LIVRES": w.SWEEP_LIVRES,
    }
    for nom, motif in motifs.items():
        # Un `%` valide est suivi de `(cle)s` ou `(cle)d`, ou doublé.
        restant = re.sub(r"%\([a-z_]+\)[sd]|%%", "", motif)
        assert "%" not in restant, f"{nom} porte un signe pour cent isolé"
