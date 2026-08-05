"""Chargement de l'export dans `tmdb_catalog`."""

from __future__ import annotations

from datetime import date

import pytest

from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

JOUR = date(2026, 8, 5)
LENDEMAIN = date(2026, 8, 6)


def _series(identifier: int, nom: str, popularite: float = 1.0, adulte: bool = False) -> dict:
    return {
        "id": identifier,
        "original_name": nom,
        "popularity": popularite,
        "adult": adulte,
    }


async def test_chargement_initial(conn):
    lues, inserees, majs = await load_catalog(
        conn, iter([_series(1399, "Game of Thrones", 412.5), _series(1396, "Breaking Bad")]), JOUR
    )

    assert (lues, inserees, majs) == (2, 2, 0)

    async with conn.cursor() as cur:
        await cur.execute("select id, original_name, popularity, exported_on from tmdb_catalog")
        assert sorted(await cur.fetchall()) == [
            (1396, "Breaking Bad", 1.0, JOUR),
            (1399, "Game of Thrones", 412.5, JOUR),
        ]


async def test_rechargement_met_a_jour_sans_dupliquer(conn):
    """L'export est quotidien : la seconde passe doit corriger la popularité,
    pas créer une deuxième ligne."""
    await load_catalog(conn, iter([_series(1399, "Game of Thrones", 412.5)]), JOUR)
    lues, inserees, majs = await load_catalog(
        conn,
        iter([_series(1399, "Game of Thrones", 300.0), _series(1396, "Breaking Bad")]),
        LENDEMAIN,
    )

    assert (lues, inserees, majs) == (2, 1, 1)

    async with conn.cursor() as cur:
        await cur.execute("select popularity, exported_on from tmdb_catalog where id = 1399")
        assert await cur.fetchone() == (300.0, LENDEMAIN)


async def test_une_serie_absente_garde_son_ancienne_date(conn):
    """C'est la détection de suppression : un id dont `exported_on` décroche
    des autres n'était plus dans le dernier export."""
    await load_catalog(conn, iter([_series(1399, "A"), _series(1396, "B")]), JOUR)
    await load_catalog(conn, iter([_series(1399, "A")]), LENDEMAIN)

    async with conn.cursor() as cur:
        await cur.execute(
            "select id from tmdb_catalog where exported_on < "
            "(select max(exported_on) from tmdb_catalog)"
        )
        assert [row[0] for row in await cur.fetchall()] == [1396]


async def test_un_id_en_double_dans_l_export_ne_fait_pas_echouer(conn):
    """Postgres refuse qu'un ON CONFLICT DO UPDATE touche deux fois la même
    ligne : sans déduplication en amont, tout le chargement échouerait."""
    lues, inserees, majs = await load_catalog(
        conn, iter([_series(1399, "A"), _series(1399, "A bis")]), JOUR
    )

    assert lues == 2
    assert inserees + majs == 1

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from tmdb_catalog")
        assert (await cur.fetchone())[0] == 1


async def test_une_ligne_sans_id_est_ignoree(conn):
    lues, _, _ = await load_catalog(conn, iter([{"original_name": "sans id"}]), JOUR)
    assert lues == 0
