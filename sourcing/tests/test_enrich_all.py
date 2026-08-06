"""L'enrichissement de tout le catalogue.

Ce qui se joue ici et pas dans `test_enrich.py` : la sélection de ce qui reste à
faire — les séries **collectées** et pas encore regardées —, le regroupement des
résolutions par lot, et le fait qu'une seconde passe ne refasse pas le travail
de la première.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from fiv_sourcing import store
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


async def _collectees(conn, *ids: int) -> None:
    """Inventaire + fiche collectée + état de collecte, pour chaque série."""
    await load_catalog(
        conn,
        iter([{"id": i, "original_name": f"Série {i}", "popularity": 1.0} for i in ids]),
        JOUR,
    )
    for identifier in ids:
        await store.store_raw(
            conn,
            source="tmdb",
            kind="tv",
            source_id=str(identifier),
            lang="fr-FR",
            http_status=200,
            payload={"id": identifier},
        )
        await store.mark_fetch(
            conn,
            source="tmdb",
            kind="tv",
            source_id=str(identifier),
            http_status=200,
            changed=True,
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


async def test_la_selection_ne_porte_que_sur_les_series_collectees(conn):
    """`riche_source` référence la fiche : une série sans fiche n'est pas
    enrichissable, donc pas sélectionnable. Elle entrera dans la sélection une
    fois la collecte passée."""
    await _collectees(conn, 1, 3)
    await load_catalog(
        conn, iter([{"id": 2, "original_name": "non collectée", "popularity": 9.0}]), JOUR
    )

    assert await pending_ids(conn) == [1, 3]


async def test_la_selection_ignore_ce_qui_a_deja_ete_regarde(conn):
    """Le critère de reprise est `fetch_state`, pas `riche_source` : la majorité
    des séries n'a pas d'item Wikidata et ne produira jamais de ligne."""
    await _collectees(conn, 1, 2, 3)
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into fetch_state (source, kind, source_id, last_fetched_at, last_status) "
            "values ('wikidata', 'lookup', '2', now(), 200)"
        )

    assert await pending_ids(conn) == [1, 3]


async def test_la_selection_respecte_limite_et_tri(conn):
    await _collectees(conn, 1, 2, 3)
    assert await pending_ids(conn, limit=2) == [1, 2]
    assert len(await pending_ids(conn, order="random")) == 3

    with pytest.raises(ValueError, match="tri inconnu"):
        await pending_ids(conn, order="au-hasard")


async def test_l_ordre_recent_prime_sur_la_popularite(conn):
    """La popularité seule ne trie pas par récence : la série de 2015 est la
    plus consultée, mais c'est la nouveauté qu'on veut traiter d'abord."""
    await _collectees(conn, 1, 2, 3)
    async with conn.cursor() as cur:
        await cur.execute("update tmdb_catalog set popularity = 100 where id = 1")
        for identifiant, jour in ((1, "2015-01-01"), (2, "2020-01-01"), (3, "2026-01-01")):
            await cur.execute(
                "update tmdb_catalog set first_air_date = %s where id = %s", (jour, identifiant)
            )

    assert await pending_ids(conn, order="recent") == [3, 2, 1]
    assert await pending_ids(conn, order="popularity") == [1, 2, 3]


async def test_les_series_sans_date_passent_en_dernier(conn):
    await _collectees(conn, 1, 2, 3)
    async with conn.cursor() as cur:
        await cur.execute("update tmdb_catalog set first_air_date = '2020-01-01' where id = 2")

    assert (await pending_ids(conn, order="recent"))[0] == 2


async def test_les_dates_se_recopient_depuis_le_brut(conn):
    """`--order recent` ne vaut que si la colonne est remplie, et elle l'est par
    dérivation : aucun appel réseau."""
    from fiv_sourcing.sources.tmdb.export import refresh_air_dates

    await _collectees(conn, 1, 2)
    async with conn.cursor() as cur:
        for identifiant, valeur in ((1, "2026-03-01"), (2, "")):
            await cur.execute(
                "insert into raw_source (source, kind, source_id, http_status, payload, "
                "payload_sha256) values ('tmdb', 'tv', %s, 200, "
                "jsonb_build_object('first_air_date', %s::text), %s)",
                (str(identifiant), valeur, bytes([100 + identifiant])),
            )

    assert await refresh_air_dates(conn) == 1

    async with conn.cursor() as cur:
        await cur.execute("select id, first_air_date from tmdb_catalog order by id")
        lignes = await cur.fetchall()

    assert lignes[0][1] == date(2026, 3, 1)
    assert lignes[1][1] is None, "une chaîne vide n'est pas une date, et ne doit pas tout annuler"


@respx.mock
async def test_un_lot_resout_toutes_les_series_en_une_requete(conn, settings: Settings):
    """C'est ce qui rend la passe tenable : 100 séries par requête SPARQL au
    lieu d'une chacune."""
    await _collectees(conn, 1, 2, 3, 4)
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
    await _collectees(conn, 1, 2, 3, 4)
    _mock((2, 4))

    report = await _lancer(conn, settings, [1, 2, 3, 4])

    async with conn.cursor() as cur:
        await cur.execute("select count(distinct id_tmdb) from riche_source")
        en_base = (await cur.fetchone())[0]

    assert report.enriched == en_base == 2


@respx.mock
async def test_le_brut_garde_une_ligne_par_serie_trouvee(conn, settings: Settings):
    """R1/R2 : la réponse du lot est redécoupée par série avant d'entrer dans le
    brut — seule la série trouvée y laisse une ligne, jamais TVmaze. Le passage,
    lui, est noté pour les trois."""
    await _collectees(conn, 1, 2, 3)
    _mock((2,))

    await _lancer(conn, settings, [1, 2, 3])

    async with conn.cursor() as cur:
        await cur.execute(
            "select source_id from raw_source where source = 'wikidata' and kind = 'lookup'"
        )
        assert [r[0] for r in await cur.fetchall()] == ["2"]
        await cur.execute("select count(*) from raw_source where source = 'tvmaze'")
        assert (await cur.fetchone())[0] == 0
        await cur.execute(
            "select count(*) from fetch_state where source = 'wikidata' and kind = 'lookup'"
        )
        assert (await cur.fetchone())[0] == 3


@respx.mock
async def test_une_seconde_passe_ne_reprend_rien(conn, settings: Settings):
    await _collectees(conn, 1, 2, 3)
    _mock((2,))

    await _lancer(conn, settings, await pending_ids(conn))
    assert await pending_ids(conn) == []


@respx.mock
async def test_une_serie_sans_item_ni_imdb_ne_declenche_aucun_appel(conn, settings: Settings):
    """Le fond de catalogue, c'est-à-dire la majorité. Une requête SPARQL de lot
    et rien d'autre."""
    await _collectees(conn, 1, 2, 3)
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
    await _collectees(conn, 1, 2)
    respx.get(url__startswith="https://query.wikidata.org/sparql").mock(
        httpx.Response(500, json={})
    )

    report = await _lancer(conn, settings, [1, 2], lot=1)

    assert report.done == 2
    assert report.errors == 2
    assert report.resolved == 0
