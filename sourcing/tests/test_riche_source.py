"""La table d'enrichissement, raccrochée au brut collecté.

Ces tests portent sur ce que le schéma garantit tout seul, parce que ce sont les
garanties dont l'enrichissement dépend sans les revérifier.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from fiv_sourcing import store
from fiv_sourcing.sources.tmdb.export import load_catalog

pytestmark = pytest.mark.integration

JOUR = date(2026, 8, 6)


async def _serie_collectee(conn, identifier: int = 1399) -> int:
    """Une série dans l'inventaire ET sa fiche dans le brut — le préalable de
    tout enrichissement. Renvoie l'id de la fiche."""
    await load_catalog(
        conn,
        iter([{"id": identifier, "original_name": "Game of Thrones", "popularity": 1.0}]),
        JOUR,
    )
    await store.store_raw(
        conn,
        source="tmdb",
        kind="tv",
        source_id=str(identifier),
        lang="fr-FR",
        http_status=200,
        payload={"id": identifier},
    )
    return (await store.latest_fiche_ids(conn, [identifier]))[identifier]


async def test_les_compteurs_sont_calcules(conn):
    """Le rapport de couverture seuille sur `content_chars` sans lire le texte :
    la colonne doit se remplir seule."""
    fiche = await _serie_collectee(conn)

    await store.upsert_riche_source(
        conn,
        raw_source_id=fiche,
        tv_id=1399,
        source="wikipedia",
        lang="ar",
        source_id="صراع العروش",
        content="أربعة",
        media=[{"type": "poster"}, {"type": "still"}],
    )
    async with conn.cursor() as cur:
        await cur.execute("select content_chars, media_count from riche_source")
        assert await cur.fetchone() == (5, 2)


async def test_les_faits_ont_leur_colonne(conn):
    """Les réponses tierces ne sont pas conservées en brut : `facts` est le seul
    lieu de vie des pays, langues et lieux. Les perdre serait définitif."""
    fiche = await _serie_collectee(conn)

    await store.upsert_riche_source(
        conn,
        raw_source_id=fiche,
        tv_id=1399,
        source="wikidata",
        source_id="Q23572",
        facts={"pays": ["US"], "lieux_tournage": ["Belfast"]},
    )
    async with conn.cursor() as cur:
        await cur.execute("select facts -> 'pays', facts -> 'lieux_tournage' from riche_source")
        assert await cur.fetchone() == (["US"], ["Belfast"])


async def test_recollecter_puis_reenrichir_met_la_reference_a_jour(conn):
    """`raw_source` est append-only : une re-collecte crée une nouvelle fiche.
    Le ré-enrichissement doit suivre la référence, pas dupliquer la série."""
    premiere_fiche = await _serie_collectee(conn)
    await store.upsert_riche_source(
        conn, raw_source_id=premiere_fiche, tv_id=1399, source="wikidata", source_id="Q23572"
    )

    await store.store_raw(
        conn,
        source="tmdb",
        kind="tv",
        source_id="1399",
        lang="fr-FR",
        http_status=200,
        payload={"id": 1399, "name": "recollectée"},
    )
    nouvelle_fiche = (await store.latest_fiche_ids(conn, [1399]))[1399]
    assert nouvelle_fiche != premiere_fiche

    await store.upsert_riche_source(
        conn, raw_source_id=nouvelle_fiche, tv_id=1399, source="wikidata", source_id="Q23572"
    )
    async with conn.cursor() as cur:
        await cur.execute("select count(*), max(raw_source_id) from riche_source")
        assert await cur.fetchone() == (1, nouvelle_fiche)


async def test_deux_langues_de_la_meme_source_cohabitent(conn):
    fiche = await _serie_collectee(conn)
    for lang in ("ar", "en"):
        await store.upsert_riche_source(
            conn,
            raw_source_id=fiche,
            tv_id=1399,
            source="wikipedia",
            lang=lang,
            source_id="Game of Thrones",
        )
    async with conn.cursor() as cur:
        await cur.execute("select count(*) from riche_source")
        assert (await cur.fetchone())[0] == 2


async def test_un_media_qui_n_est_pas_un_tableau_est_refuse(conn):
    fiche = await _serie_collectee(conn)

    with pytest.raises(psycopg.errors.CheckViolation) as erreur:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into riche_source (raw_source_id, id_tmdb, source, source_id, media) "
                "values (%s, 1399, 'tvmaze', '82', '{}'::jsonb)",
                (fiche,),
            )

    assert "riche_source_media_is_array" in str(erreur.value)


async def test_une_fiche_inexistante_est_refusee(conn):
    """L'enrichissement se raccroche au brut collecté : une référence vers une
    fiche qui n'existe pas doit échouer à l'écriture, pas produire une ligne
    orpheline."""
    await _serie_collectee(conn)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into riche_source (raw_source_id, id_tmdb, source, source_id) "
                "values (999999999, 1399, 'wikidata', 'Q1')"
            )
