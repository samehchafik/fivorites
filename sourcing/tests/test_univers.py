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

from fiv_sourcing.sources.tmdb.export import export_url, load_catalog
from fiv_sourcing.univers import FILMS, SERIES, resoudre


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
    # `original_title` et non `original_name` : c'est le champ que porte
    # l'export des films, TMDB n'ayant jamais unifié les deux vocabulaires.
    await load_catalog(
        conn,
        iter([{"id": 1399, "original_title": "Fight Club", "popularity": 60.0}]),
        date(2026, 8, 12),
        univers=FILMS,
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


def test_le_titre_de_l_export_change_de_nom_selon_l_univers() -> None:
    """Le piège silencieux : lire `original_name` sur un export de films
    donnerait 1,1 million de lignes sans titre, et aucune erreur."""
    assert SERIES.titre_export == "original_name"
    assert FILMS.titre_export == "original_title"


def test_les_deux_exports_ont_deux_noms_de_fichier() -> None:
    assert export_url(date(2026, 8, 12), SERIES).endswith("tv_series_ids_08_12_2026.json.gz")
    assert export_url(date(2026, 8, 12), FILMS).endswith("movie_ids_08_12_2026.json.gz")


def test_un_univers_inconnu_s_arrete_tout_de_suite() -> None:
    """Sans cette liste fermée, une faute de frappe créerait un troisième
    univers dans `tmdb_catalog` qui ne se verrait qu'à l'écran vide."""
    import pytest

    assert resoudre(None) is SERIES
    with pytest.raises(ValueError, match="univers inconnu"):
        resoudre("films")
