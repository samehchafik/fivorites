"""L'enrichissement de tout le catalogue.

Ce qui se joue ici et pas dans `test_enrich.py` : la sélection de ce qui reste à
faire, le regroupement des résolutions par lot, et le fait qu'une seconde passe
ne refasse pas le travail de la première.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.enrich import build_clients, build_fetcher, enrich_all, pending_ids
from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

JOUR = date(2026, 8, 6)


def _lot(*trouvees: int) -> dict:
    """Réponse SPARQL groupée : seules les séries listées ont un item."""
    return {
        "results": {
            "bindings": [
                {
                    "tmdb": {"value": str(i)},
                    "item": {"value": f"http://www.wikidata.org/entity/Q{i}"},
                    "tvmaze": {"value": str(1000 + i)},
                }
                for i in trouvees
            ]
        }
    }


async def _catalogue(conn, *ids: int) -> None:
    await load_catalog(
        conn,
        iter([{"id": i, "original_name": f"Série {i}", "popularity": 1.0} for i in ids]),
        JOUR,
    )


def _mock(trouvees: tuple[int, ...]) -> None:
    respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(200, json=_lot(*trouvees))
    )
    respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        httpx.Response(200, json={"entities": {}})
    )
    respx.get(url__startswith="https://api.tvmaze.com/shows/").mock(
        httpx.Response(200, json={"id": 1, "name": "X", "_embedded": {"episodes": []}})
    )


async def _lancer(conn, settings: Settings, ids: list[int], **kwargs):
    fetcher = build_fetcher(settings)
    async with fetcher:
        return await enrich_all(conn, build_clients(fetcher), ids, languages=("fr",), **kwargs)


async def test_la_selection_ignore_ce_qui_a_deja_ete_regarde(conn, settings: Settings):
    """Le critère est `fetch_state`, pas `series_source` : la majorité des
    séries n'aura jamais de ligne, et on ne doit pas les retenter sans fin."""
    await _catalogue(conn, 1, 2, 3)
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into fetch_state (source, kind, source_id, last_fetched_at, last_status) "
            "values ('wikidata', 'lookup', '2', now(), 200)"
        )

    assert await pending_ids(conn) == [1, 3]


async def test_la_selection_respecte_limite_et_tri(conn, settings: Settings):
    await _catalogue(conn, 1, 2, 3)
    assert await pending_ids(conn, limit=2) == [1, 2]
    assert len(await pending_ids(conn, order="random")) == 3

    with pytest.raises(ValueError, match="tri inconnu"):
        await pending_ids(conn, order="au-hasard")


@respx.mock
async def test_un_lot_resout_toutes_les_series_en_une_requete(conn, settings: Settings):
    """C'est ce qui rend la passe tenable : 100 séries par requête SPARQL au
    lieu d'une chacune."""
    await _catalogue(conn, 1, 2, 3, 4)
    sparql = respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(200, json=_lot(2, 4))
    )
    _mock((2, 4))

    report = await _lancer(conn, settings, [1, 2, 3, 4], lot=100)

    assert sparql.call_count == 1
    assert report.selected == 4
    assert report.done == 4
    assert report.resolved == 2


@respx.mock
async def test_le_compteur_enrichies_correspond_a_ce_qui_est_en_base(conn, settings: Settings):
    """La ligne `wikidata` est écrite pendant la résolution du lot, hors du
    rapport de détail. Sans report explicite, `enriched` annoncerait moins de
    séries qu'il n'y en a réellement dans `series_source`."""
    await _catalogue(conn, 1, 2, 3, 4)
    _mock((2, 4))

    report = await _lancer(conn, settings, [1, 2, 3, 4])

    async with conn.cursor() as cur:
        await cur.execute("select count(distinct id_tmdb) from series_source")
        en_base = (await cur.fetchone())[0]

    assert report.enriched == en_base == 2


@respx.mock
async def test_chaque_serie_garde_sa_propre_ligne_de_brut(conn, settings: Settings):
    """Le lot est une optimisation de transport. Si `raw_source` portait une
    ligne pour cent séries, ni la fraîcheur ni l'empreinte ne voudraient plus
    rien dire pour aucune d'elles."""
    await _catalogue(conn, 1, 2, 3)
    _mock((2,))

    await _lancer(conn, settings, [1, 2, 3])

    async with conn.cursor() as cur:
        await cur.execute(
            "select source_id from raw_source where source = 'wikidata' and kind = 'lookup' "
            "order by source_id"
        )
        assert [r[0] for r in await cur.fetchall()] == ["1", "2", "3"]

        # Y compris celles qui n'ont pas d'item : « on a regardé, il n'y a rien »
        # est une information qu'on veut garder.
        await cur.execute(
            "select count(*) from fetch_state where source = 'wikidata' and kind = 'lookup'"
        )
        assert (await cur.fetchone())[0] == 3


@respx.mock
async def test_une_seconde_passe_ne_reprend_rien(conn, settings: Settings):
    await _catalogue(conn, 1, 2, 3)
    _mock((2,))

    await _lancer(conn, settings, await pending_ids(conn))
    reste = await pending_ids(conn)

    assert reste == []


@respx.mock
async def test_une_serie_sans_item_ni_imdb_ne_declenche_aucun_appel(conn, settings: Settings):
    """Le fond de catalogue, c'est-à-dire la majorité. Une requête SPARQL de lot
    et rien d'autre — sinon la passe coûterait des jours de plus pour rien."""
    await _catalogue(conn, 1, 2, 3)
    _mock(())
    entites = respx.get(url__startswith="https://www.wikidata.org/w/api.php")
    tvmaze = respx.get(url__startswith="https://api.tvmaze.com/")

    report = await _lancer(conn, settings, [1, 2, 3])

    assert report.resolved == 0
    assert report.enriched == 0
    assert report.requests == 1, "une seule requête : le lot SPARQL"
    assert not entites.called
    assert not tvmaze.called


@respx.mock
async def test_un_lot_en_echec_n_interrompt_pas_la_passe(conn, settings: Settings):
    """Wikidata peut renvoyer un 500 sur une requête lourde. Les tranches
    suivantes doivent quand même passer."""
    await _catalogue(conn, 1, 2)
    respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(500, json={})
    )

    report = await _lancer(conn, settings, [1, 2], lot=1)

    assert report.done == 2
    assert report.errors == 2
    assert report.resolved == 0
