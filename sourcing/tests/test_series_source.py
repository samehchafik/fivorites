"""La table d'enrichissement externe.

Aucun code applicatif ne l'alimente encore — c'est le lot 3. Ces tests portent
sur ce que le schéma garantit tout seul, parce que ce sont justement les
garanties dont la collecte à venir va dépendre sans les revérifier.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

JOUR = date(2026, 8, 6)


async def _catalogue(conn, identifier: int = 1399) -> int:
    await load_catalog(
        conn,
        iter([{"id": identifier, "original_name": "Game of Thrones", "popularity": 1.0}]),
        JOUR,
    )
    return identifier


async def test_les_compteurs_sont_calcules(conn):
    """Le rapport de couverture seuille sur `content_chars` sans lire le texte :
    il faut que la colonne se remplisse seule, sinon elle mentira le jour où
    quelqu'un écrira un UPDATE en oubliant de la recalculer."""
    id_tmdb = await _catalogue(conn)

    async with conn.cursor() as cur:
        await cur.execute(
            "insert into series_source (id_tmdb, source, lang, source_id, content, media) "
            "values (%s, 'wikipedia', 'ar', 'باب الحارة', %s, %s)",
            (id_tmdb, "أربعة", '[{"type": "poster"}, {"type": "still"}]'),
        )
        await cur.execute("select content_chars, media_count from series_source")
        assert await cur.fetchone() == (5, 2)


async def test_une_serie_sans_texte_compte_zero_et_non_null(conn):
    """Une entrée Wikidata n'apporte que des faits. `sum(content_chars)` sur une
    série doit rester un nombre, pas devenir NULL parce qu'une ligne est vide."""
    id_tmdb = await _catalogue(conn)

    async with conn.cursor() as cur:
        await cur.execute(
            "insert into series_source (id_tmdb, source, source_id) "
            "values (%s, 'wikidata', 'Q23572')",
            (id_tmdb,),
        )
        await cur.execute("select coalesce(sum(content_chars), -1) from series_source")
        assert (await cur.fetchone())[0] == 0


async def test_deux_langues_de_la_meme_source_cohabitent(conn):
    """L'article arabe et l'article anglais sont deux matières distinctes, pas
    deux versions d'une même ligne."""
    id_tmdb = await _catalogue(conn)

    async with conn.cursor() as cur:
        for lang in ("ar", "en"):
            await cur.execute(
                "insert into series_source (id_tmdb, source, lang, source_id) "
                "values (%s, 'wikipedia', %s, 'Game of Thrones')",
                (id_tmdb, lang),
            )
        await cur.execute("select count(*) from series_source")
        assert (await cur.fetchone())[0] == 2


async def test_recollecter_la_meme_source_ne_duplique_pas(conn):
    """Une seconde passe doit remplacer, pas empiler : la clé primaire porte
    (série, source, langue)."""
    id_tmdb = await _catalogue(conn)

    async with conn.cursor() as cur:
        for texte in ("premier jet", "article complété"):
            await cur.execute(
                "insert into series_source (id_tmdb, source, lang, source_id, content) "
                "values (%s, 'wikipedia', 'ar', 'X', %s) "
                "on conflict (id_tmdb, source, lang) do update set content = excluded.content",
                (id_tmdb, texte),
            )
        await cur.execute("select content from series_source")
        assert (await cur.fetchone())[0] == "article complété"


async def test_un_media_qui_n_est_pas_un_tableau_est_refuse(conn):
    """`media_count` casserait à l'insertion, avec un message sur une fonction
    interne. La contrainte nommée dit ce qui ne va pas."""
    id_tmdb = await _catalogue(conn)

    with pytest.raises(psycopg.errors.CheckViolation) as erreur:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into series_source (id_tmdb, source, source_id, media) "
                "values (%s, 'tvmaze', '82', '{}'::jsonb)",
                (id_tmdb,),
            )

    assert "series_source_media_is_array" in str(erreur.value)


async def test_une_serie_hors_catalogue_est_refusee(conn):
    """L'enrichissement porte sur des séries connues de TMDB. Une faute de
    frappe sur un id doit échouer à l'écriture, pas produire une ligne
    orpheline que personne ne relira jamais."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into series_source (id_tmdb, source, source_id) "
                "values (%s, 'wikidata', 'Q1')",
                (999_999_999,),
            )
