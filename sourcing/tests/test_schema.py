"""Où vivent les tables.

Une base par projet, un schéma par domaine. Ces tests échouent si une migration
future crée par distraction une table dans `public` — le genre de dérive qui ne
se voit qu'une fois qu'un deuxième domaine est arrivé et qu'il est trop tard.
"""

from __future__ import annotations

import pytest

from fiv_sourcing.config import Settings

pytestmark = pytest.mark.integration


async def test_les_tables_de_collecte_sont_dans_le_schema_sourcing(conn, settings: Settings):
    async with conn.cursor() as cur:
        await cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = %s order by table_name",
            (settings.db_schema,),
        )
        tables = [row[0] for row in await cur.fetchall()]

    assert tables == ["fetch_state", "raw_source", "riche_source", "tmdb_catalog"]


async def test_public_ne_contient_que_l_historique_des_migrations(conn):
    """L'historique vaut pour la base entière, pas pour un domaine : c'est la
    seule table qui a sa place dans `public`."""
    async with conn.cursor() as cur:
        await cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' order by table_name"
        )
        tables = [row[0] for row in await cur.fetchall()]

    assert tables == ["schema_migrations"]


async def test_le_search_path_rend_les_tables_accessibles_sans_prefixe(conn, settings: Settings):
    """Le code applicatif écrit `raw_source`, pas `sourcing.raw_source` :
    changer de schéma doit rester un réglage, pas une réécriture de SQL."""
    async with conn.cursor() as cur:
        # `to_regclass('raw_source')::text` omettrait le préfixe dès lors que le
        # schéma est sur le search_path — il faut donc lire le namespace réel
        # pour vérifier où le nom nu se résout.
        await cur.execute(
            "select n.nspname from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where c.oid = to_regclass('raw_source')"
        )
        row = await cur.fetchone()

    assert row is not None, "`raw_source` non résolu : le search_path n'est pas posé"
    assert row[0] == settings.db_schema
