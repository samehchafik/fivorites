"""L'univers livres dans l'admin — vignettes, fiche, sources, par le pivot.

Un livre n'a pas d'identifiant TMDB : sa vignette est keyée par
`sourcing.oeuvre.id`, sa matière vient de `riche_source` (Wikidata, Open
Library, Wikipédia), et sa fiche s'assemble sans brut. Ces tests figent les
trois lectures — grille, fiche, sources — et la jointure des notes par le
pivot, qui est LE point où livres et séries divergent.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from conftest import requires_db
from fiv_admin.catalog import (
    CardQuery,
    fetch_cards,
    fetch_rich,
    fetch_work,
    refresh_cards,
)

pytestmark = [pytest.mark.integration, requires_db]

FACTS_WIKIDATA = {
    "annee": 1967,
    "pays": ["CO"],
    "langues": ["es"],
    "auteurs": [{"qid": "Q5878", "nom": "Gabriel García Márquez"}],
    "ids": {"wikidata": "Q189378", "openlibrary": "OL27258W"},
}

FACTS_OPENLIBRARY = {
    "titre": "Cien años de soledad",
    "editions": {
        "par_langue": [
            {"langue": "es", "nombre": 7, "isbn": "9780307474728"},
            {"langue": "fr", "nombre": 5, "isbn": "9782020238113"},
        ],
        "total": 64,
        "sans_langue": 15,
        "tronque": False,
    },
    "ids": {"openlibrary": "OL27258W"},
}


async def seed_livre(conn: psycopg.AsyncConnection) -> int:
    """Un livre enrichi, tel que le crawler du sourcing le laisse."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into oeuvre (univers, wikidata_qid, id_openlibrary, titre, annee)
            values ('livres', 'Q189378', 'OL27258W', 'Cien años de soledad', 1967)
            returning id
            """
        )
        oeuvre_id = (await cur.fetchone())[0]

    for source, lang, source_id, content, facts, resolved in (
        ("wikidata", "", "Q189378", None, FACTS_WIKIDATA, "sweep"),
        ("openlibrary", "", "OL27258W", "La saga des Buendía.", FACTS_OPENLIBRARY, "p648"),
        ("wikipedia", "fr", "Cent ans de solitude", "Le roman de Macondo.", {}, "sitelink"),
    ):
        await conn.execute(
            """
            insert into riche_source (oeuvre_id, source, lang, source_id,
                                      content, facts, resolved_by, fetched_at)
            values (%s, %s, %s, %s, %s, %s::jsonb, %s, now())
            """,
            (oeuvre_id, source, lang, source_id, content, json.dumps(facts), resolved),
        )
    await refresh_cards(conn)
    return oeuvre_id


async def test_la_vignette_livre_s_assemble_depuis_riche_source(
    conn: psycopg.AsyncConnection,
) -> None:
    oeuvre_id = await seed_livre(conn)

    rows, total = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book"))

    assert total == 1
    carte = rows[0]
    assert carte["id"] == oeuvre_id, "la clé est le pivot, pas un id TMDB"
    assert carte["name"] == "Cien años de soledad"
    assert carte["overview"] == "Le roman de Macondo."
    assert carte["originalLanguage"] == "es"
    assert carte["originCountry"] == ["CO"]
    assert carte["year"] == 1967
    assert carte["posterPath"] is None


async def test_les_notes_du_livre_se_joignent_par_le_pivot(
    conn: psycopg.AsyncConnection,
) -> None:
    """LE point de divergence avec les séries : `notation.score` désigne le
    livre par son pivot, et la vignette porte le même identifiant — la
    jointure des vecteurs doit donc passer par `o.id`, jamais `o.id_tmdb`."""
    oeuvre_id = await seed_livre(conn)
    await conn.execute(
        f"""
        insert into notation.score
            (oeuvre_id, axe, valeur, confiance, rubric_version, modele,
             input_sha256, prompt_sha256, scored_at)
        values ({oeuvre_id}, 'luminosite', 7, 0.8, 'v1', 'gpt-test',
                'sha-in', 'sha-p', now())
        """
    )

    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book"))

    assert rows[0]["axisScores"] == {"luminosite": 7.0}


async def test_la_fiche_livre_s_assemble_sans_brut(conn: psycopg.AsyncConnection) -> None:
    oeuvre_id = await seed_livre(conn)

    fiche = await fetch_work(conn, oeuvre_id, "fr-FR", "book")

    assert fiche is not None
    assert fiche["name"] == "Cien años de soledad"
    assert fiche["overview"] == "Le roman de Macondo."
    assert fiche["translated"] == {"lang": "fr-FR", "name": False, "overview": True}
    assert fiche["createdBy"] == ["Gabriel García Márquez"]
    assert fiche["originalLanguage"] == "es"
    assert fiche["firstAirDate"] == "1967-01-01"
    # Les traductions affichées sont les langues d'édition Open Library,
    # complétées des articles Wikipédia collectés.
    assert fiche["translations"] == ["es", "fr"]
    assert fiche["externalIds"] == {
        "wikidata_id": "Q189378",
        "openlibrary_id": "OL27258W",
    }
    assert fiche["seasons"] == [] and fiche["cast"] == []


async def test_les_sources_du_livre_se_lisent_par_le_pivot(
    conn: psycopg.AsyncConnection,
) -> None:
    oeuvre_id = await seed_livre(conn)

    riche = await fetch_rich(conn, oeuvre_id, "book")

    assert riche["oeuvre"] is not None
    assert riche["oeuvre"]["openlibraryId"] == "OL27258W"
    assert [bloc["source"] for bloc in riche["sources"]] == [
        "openlibrary",
        "wikidata",
        "wikipedia",
    ]
    ol = next(bloc for bloc in riche["sources"] if bloc["source"] == "openlibrary")
    assert ol["entries"][0]["facts"]["editions"]["total"] == 64


async def test_l_extraction_es_indexe_le_livre_par_le_pivot(
    conn: psycopg.AsyncConnection,
) -> None:
    """La requête d'extraction contre une vraie base : l'inventaire des livres
    est la projection elle-même (pas de `tmdb_catalog`), et l'identité se
    joint sur `o.id`."""
    from psycopg.rows import dict_row

    from fiv_admin.media import MEDIA
    from fiv_admin.search import construire_doc, parametres_extraction, requete_extraction

    oeuvre_id = await seed_livre(conn)
    media = MEDIA["book"]

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(requete_extraction(media), parametres_extraction(media))
        rows = await cur.fetchall()

    assert len(rows) == 1
    doc = construire_doc(rows[0], media.univers)
    assert doc["oeuvre_id"] == oeuvre_id
    assert doc["univers"] == "livres"
    assert doc["name"] == "Cien años de soledad"
    assert doc["original_language"] == "es"
    assert doc["annee"] == 1967
    assert doc["has_overview"] is True


async def test_l_extraction_graphe_porte_les_auteurs(
    conn: psycopg.AsyncConnection,
) -> None:
    from psycopg.rows import dict_row

    from fiv_admin.graphe import construire_oeuvre, parametres_extraction, requete_extraction
    from fiv_admin.media import MEDIA

    oeuvre_id = await seed_livre(conn)
    media = MEDIA["book"]

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(requete_extraction(media), parametres_extraction(media))
        rows = await cur.fetchall()

    assert len(rows) == 1
    noeud = construire_oeuvre(rows[0], media.univers)
    assert noeud["oeuvreId"] == oeuvre_id
    assert noeud["props"]["idTmdb"] is None
    assert noeud["props"]["titre"] == "Cien años de soledad"
    assert noeud["creation"] == [
        {"cle": "wd:Q5878", "nom": "Gabriel García Márquez", "photo": None}
    ]
    assert noeud["distribution"] == [] and noeud["realisation"] == []
