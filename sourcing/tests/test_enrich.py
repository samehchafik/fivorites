"""L'enrichissement de bout en bout, réseau simulé.

Nécessite Postgres. Ce qu'on vérifie ici n'est pas le parsing — il a ses tests —
mais l'enchaînement : ce qui atterrit dans `riche_source`, par quelle voie le
raccordement s'est fait, et le fait que `raw_source` reste exclusivement TMDB.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from fiv_sourcing import store
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


async def _serie_collectee(conn, *, avec_imdb: bool = False) -> int:
    """L'inventaire + la fiche collectée. Renvoie l'id de la fiche."""
    await load_catalog(
        conn,
        iter([{"id": TV_ID, "original_name": "Game of Thrones", "popularity": 1.0}]),
        date(2026, 8, 6),
    )
    payload: dict = {"id": TV_ID}
    if avec_imdb:
        payload["external_ids"] = {"imdb_id": IMDB}
    await store.store_raw(
        conn,
        source="tmdb",
        kind="tv",
        source_id=str(TV_ID),
        lang="fr-FR",
        http_status=200,
        payload=payload,
    )
    return (await store.latest_fiche_ids(conn, [TV_ID]))[TV_ID]


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
    fiche = await _serie_collectee(conn)
    _mock(SPARQL_TROUVE)

    report = await _enrichir(conn, settings)

    assert report.qid == QID
    assert report.resolved_by == "p4983"
    assert set(report.sources) == {"wikidata", "wikipedia/fr", "wikipedia/en", "tvmaze"}
    assert not report.errors

    async with conn.cursor() as cur:
        await cur.execute(
            "select raw_source_id, id_tmdb, source, lang, source_id, resolved_by, "
            "content_chars, media_count from riche_source order by source, lang"
        )
        assert await cur.fetchall() == [
            (fiche, TV_ID, "tvmaze", "", "82", "p8600", len("Ned part."), 1),
            (fiche, TV_ID, "wikidata", "", QID, "p4983", 0, 0),
            (fiche, TV_ID, "wikipedia", "en", "Game of Thrones", "sitelink", 15, 0),
            (fiche, TV_ID, "wikipedia", "fr", "Le Trône de fer", "sitelink", 15, 0),
        ]


@respx.mock
async def test_les_faits_sont_au_format_canonique(conn, settings: Settings):
    """R5 : mêmes clés quelle que soit la source — la couche 1 ne lira jamais
    un format propriétaire."""
    await _serie_collectee(conn)
    _mock(SPARQL_TROUVE)

    await _enrichir(conn, settings)

    async with conn.cursor() as cur:
        await cur.execute("select facts from riche_source where source = 'wikidata'")
        wikidata_facts = (await cur.fetchone())[0]
        await cur.execute("select facts from riche_source where source = 'tvmaze'")
        tvmaze_facts = (await cur.fetchone())[0]

    assert wikidata_facts["pays"] == ["US"]
    assert wikidata_facts["lieux"] == [{"type": "tournage", "nom": "Belfast"}]
    assert wikidata_facts["ids"] == {"wikidata": QID, "imdb": IMDB, "tvmaze": 82}
    assert tvmaze_facts["diffuseur"] == "HBO"
    assert tvmaze_facts["annee"] == 2011
    assert tvmaze_facts["statut"] == "terminee"
    assert tvmaze_facts["calendrier"] == {"jours": ["Sunday"], "heure": "21:00"}
    assert tvmaze_facts["episodes"] == {"total": 1, "dates": 1, "resumes": 1}


@respx.mock
async def test_le_brut_porte_wikimedia_mais_jamais_tvmaze(conn, settings: Settings):
    """R1 : le brut de Wikidata et Wikipédia rejoint celui de TMDB — c'est ce
    qui rend l'extraction rejouable. TVmaze, enrichissement pur, n'y entre
    jamais."""
    await _serie_collectee(conn)
    _mock(SPARQL_TROUVE)

    await _enrichir(conn, settings)

    async with conn.cursor() as cur:
        await cur.execute(
            "select source, kind, source_id, count(*) from raw_source "
            "group by 1, 2, 3 order by 1, 2, 3"
        )
        assert await cur.fetchall() == [
            ("tmdb", "tv", str(TV_ID), 1),
            ("wikidata", "entity", QID, 1),
            # Tout le brut d'une série se retrouve par UNE clé — l'article
            # n'est pas keyé par son titre, qui dépend de la langue.
            ("wikidata", "lookup", str(TV_ID), 1),
            ("wikipedia", "article", str(TV_ID), 2),
        ]


@respx.mock
async def test_rejouer_remplace_la_derivation_sans_l_empiler(conn, settings: Settings):
    await _serie_collectee(conn)
    _mock(SPARQL_TROUVE)

    await _enrichir(conn, settings)
    second = await _enrichir(conn, settings)

    assert set(second.sources) == {"wikidata", "wikipedia/fr", "wikipedia/en", "tvmaze"}

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from riche_source")
        assert (await cur.fetchone())[0] == 4
        # R2 : contenu inchangé, aucune ligne de brut en plus — la déduplication
        # par empreinte tient la règle « jamais le même contenu deux fois ».
        await cur.execute("select count(*) from raw_source")
        assert (await cur.fetchone())[0] == 5


@respx.mock
async def test_une_serie_non_collectee_est_refusee(conn, settings: Settings):
    """`riche_source` référence la fiche : sans collecte, rien à raccrocher.
    Le refus doit être un message, pas une violation de contrainte."""
    await load_catalog(
        conn, iter([{"id": TV_ID, "original_name": "X", "popularity": 1.0}]), date(2026, 8, 6)
    )

    report = await _enrichir(conn, settings)

    assert report.sources == []
    assert report.errors == ["série non collectée — `tmdb fetch` d'abord"]
    assert report.requests == 0, "aucun appel réseau pour une série non enrichissable"


@respx.mock
async def test_une_serie_inconnue_de_wikidata_n_ecrit_rien(conn, settings: Settings):
    await _serie_collectee(conn)
    _mock(SPARQL_VIDE)

    report = await _enrichir(conn, settings)

    assert report.qid is None
    assert report.sources == []
    assert not report.errors

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from riche_source")
        assert (await cur.fetchone())[0] == 0
        # La tentative est tracée : on saura qu'on a déjà regardé.
        await cur.execute("select source, kind from fetch_state where source = 'wikidata'")
        assert await cur.fetchall() == [("wikidata", "lookup")]


@respx.mock
async def test_l_appariement_par_titre_exige_l_imdb(conn, settings: Settings):
    """Sans item Wikidata et sans `imdb_id` collecté, la recherche par titre ne
    peut rien confirmer : on n'écrit pas plutôt que d'écrire au hasard."""
    await _serie_collectee(conn)
    _mock(SPARQL_VIDE)
    recherche = respx.get(url__startswith="https://api.tvmaze.com/search/shows").mock(
        httpx.Response(200, json=[{"score": 30.0, "show": {"id": 999, "externals": {}}}])
    )

    report = await _enrichir(conn, settings)

    assert report.sources == []
    assert not recherche.called, "sans imdb_id, la recherche est inutile — ne pas la lancer"


@respx.mock
async def test_l_imdb_de_la_fiche_ouvre_tvmaze_sans_item_wikidata(conn, settings: Settings):
    """Le rattrapage qui reste quand Wikidata ignore la série : l'`imdb_id` de
    la fiche collectée mène au lookup TVmaze."""
    await _serie_collectee(conn, avec_imdb=True)
    _mock(SPARQL_VIDE)
    respx.get(url__startswith="https://api.tvmaze.com/lookup/shows").mock(
        httpx.Response(200, json={"id": 82})
    )

    report = await _enrichir(conn, settings)

    assert report.sources == ["tvmaze"]
    async with conn.cursor() as cur:
        await cur.execute("select resolved_by from riche_source where source = 'tvmaze'")
        assert (await cur.fetchone())[0] == "imdb"
