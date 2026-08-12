"""L'univers dans l'identité : ce que le lot 12 rend impossible.

Trois faits, et ils sont la raison d'être de la migration `012_univers.sql` :

1. deux univers peuvent porter le même identifiant TMDB sans se marcher dessus ;
2. charger l'export d'un univers n'écrase pas l'autre ;
3. le pivot d'identité naît à la collecte, pas à l'enrichissement.

Le premier point n'est pas théorique : `1399` est *Game of Thrones* côté séries
et un tout autre film côté films. Avant cette migration, l'upsert de l'export
visait `on conflict (id)` sur une table dont `id` était la clé primaire — le
premier export de films aurait remplacé 228 953 séries en silence.
"""

from __future__ import annotations

from datetime import date

import psycopg

from fiv_sourcing.sources.tmdb.export import load_catalog


async def test_le_meme_identifiant_vit_dans_deux_univers(conn: psycopg.AsyncConnection) -> None:
    await conn.execute(
        "insert into tmdb_catalog (univers, id, original_name, popularity, exported_on) values"
        " ('series', 1399, 'Game of Thrones', 400, current_date),"
        " ('movies', 1399, 'Un film qui porte le meme numero', 12, current_date)"
    )

    async with conn.cursor() as cur:
        await cur.execute("select univers, original_name from tmdb_catalog order by univers")
        assert await cur.fetchall() == [
            ("movies", "Un film qui porte le meme numero"),
            ("series", "Game of Thrones"),
        ]


async def test_charger_un_export_n_ecrase_pas_l_autre_univers(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le scénario exact qu'on a failli jouer sur le serveur.

    L'export des films et celui des séries partagent leurs numéros. Chargé sans
    univers, le second aurait remplacé le titre, la popularité et la date
    d'export du premier — sans erreur et sans retour possible, le brut collecté
    restant, lui, rangé sous l'ancien identifiant.
    """
    await load_catalog(
        conn,
        iter([{"id": 1399, "original_name": "Game of Thrones", "popularity": 400.0}]),
        date(2026, 8, 12),
    )
    await load_catalog(
        conn,
        iter([{"id": 1399, "original_name": "Fight Club", "popularity": 60.0}]),
        date(2026, 8, 12),
        univers="movies",
    )

    async with conn.cursor() as cur:
        await cur.execute(
            "select original_name from tmdb_catalog where univers = 'series' and id = 1399"
        )
        assert await cur.fetchone() == ("Game of Thrones",), (
            "la série a survécu à l'arrivée du film"
        )
        await cur.execute("select count(*) from tmdb_catalog")
        assert await cur.fetchone() == (2,)


async def test_le_pivot_nait_a_la_collecte(conn: psycopg.AsyncConnection) -> None:
    """Une œuvre existe dès que sa fiche est téléchargée.

    C'est ce qui permet à l'administration de noter une série sans l'avoir
    enrichie — elle lit le pivot, elle ne l'écrit jamais, `sourcing` lui étant
    fermé en écriture.
    """
    from fiv_sourcing.sources.tmdb.collect import collect_series

    class FauxClient:
        season_languages = ("en-US",)

        async def series(self, tv_id: int):
            return type(
                "R",
                (),
                {"status": 200, "ok": True, "error": None, "payload": {"seasons": []}},
            )()

    await collect_series(conn, FauxClient(), 4242)

    async with conn.cursor() as cur:
        await cur.execute("select univers, id_tmdb from oeuvre")
        assert await cur.fetchall() == [("series", 4242)]


async def test_une_fiche_absente_de_tmdb_ne_cree_pas_d_oeuvre(
    conn: psycopg.AsyncConnection,
) -> None:
    """Un 404 dit quelque chose sur la source, pas sur l'existence d'une œuvre."""
    from fiv_sourcing.sources.tmdb.collect import collect_series

    class FauxClient404:
        season_languages = ("en-US",)

        async def series(self, tv_id: int):
            return type(
                "R", (), {"status": 404, "ok": False, "error": "HTTP 404", "payload": None}
            )()

    await collect_series(conn, FauxClient404(), 999_999)

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from oeuvre")
        assert await cur.fetchone() == (0,)


async def test_le_pivot_ne_depend_pas_de_l_inventaire(conn: psycopg.AsyncConnection) -> None:
    """Une série collectée avant d'entrer dans l'export doit pouvoir exister.

    `tmdb_catalog` est une base de sondage alimentée une fois par jour ; une
    série créée aujourd'hui apparaît dans `/tv/changes` — donc peut être
    collectée — avant d'entrer dans l'export de demain. Une clé étrangère du
    pivot vers l'inventaire ferait échouer `tmdb fetch --id` sur une nouveauté
    parfaitement réelle.
    """
    from fiv_sourcing import store

    faits = await store.ensure_oeuvres(conn, [7777])

    assert list(faits) == [7777]
    async with conn.cursor() as cur:
        await cur.execute("select count(*) from tmdb_catalog where id = 7777")
        assert await cur.fetchone() == (0,), "aucune ligne d'inventaire, et pourtant l'œuvre existe"
