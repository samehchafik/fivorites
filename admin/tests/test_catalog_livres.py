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
    "sitelinks": 99,
    "pays": ["CO"],
    "langues": ["es"],
    "auteurs": [{"qid": "Q5878", "nom": "Gabriel García Márquez"}],
    "genres": [
        {"qid": "Q1submit", "nom": ""},  # sans libellé : écarté par la projection
        {"qid": "Q193606", "nom": "réalisme magique"},
    ],
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

    couverture = [{"type": "poster", "url": "https://covers.openlibrary.org/b/id/283860-L.jpg"}]
    for source, lang, source_id, content, facts, media, resolved in (
        ("wikidata", "", "Q189378", None, FACTS_WIKIDATA, [], "sweep"),
        (
            "openlibrary",
            "",
            "OL27258W",
            "La saga des Buendía.",
            FACTS_OPENLIBRARY,
            couverture,
            "p648",
        ),
        ("wikipedia", "fr", "Cent ans de solitude", "Le roman de Macondo.", {}, [], "sitelink"),
    ):
        await conn.execute(
            """
            insert into riche_source (oeuvre_id, source, lang, source_id,
                                      content, facts, media, resolved_by, fetched_at)
            values (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, now())
            """,
            (
                oeuvre_id,
                source,
                lang,
                source_id,
                content,
                json.dumps(facts),
                json.dumps(media),
                resolved,
            ),
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
    # Le titre d'affichage est celui de l'article Wikipédia de la langue
    # demandée — jamais le libellé Wikidata, servi avec une préférence
    # anglaise. C'est ce qui affichait tout en anglais quelle que soit la
    # langue (constaté en production le 2026-08-22).
    assert carte["name"] == "Cent ans de solitude"
    assert carte["originalName"] == "Cien años de soledad"
    assert carte["overview"] == "Le roman de Macondo."
    assert carte["originalLanguage"] == "es"
    assert carte["originCountry"] == ["CO"]
    assert carte["year"] == 1967
    assert carte["posterPath"] == "https://covers.openlibrary.org/b/id/283860-L.jpg", (
        "la couverture Open Library, en URL complète — pas un chemin TMDB"
    )


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
    assert fiche["name"] == "Cent ans de solitude", "le titre de l'article fr"
    assert fiche["overview"] == "Le roman de Macondo."
    assert fiche["translated"] == {"lang": "fr-FR", "name": True, "overview": True}
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
    # La fiche affiche « Popularité » depuis catalog.popularity, comme les
    # autres univers — pour un livre c'est sa notoriété Wikipédia.
    assert fiche["catalog"] == {"popularity": 99.0, "adult": None, "exportedOn": None}
    assert fiche["posterPath"] == "https://covers.openlibrary.org/b/id/283860-L.jpg"
    assert fiche["gallery"]["posters"] == ["https://covers.openlibrary.org/b/id/283860-L.jpg"]


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


async def test_l_hydratation_es_respecte_l_ordre_et_le_pivot_bigint(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le chemin ES→SQL : ES rend des ids, le SQL hydrate dans cet ordre.
    Les ids des livres sont des BIGINT (le pivot) là où ES les transmet en
    integer[] — Postgres 13 refusait array_position sans cast explicite,
    et le serveur a affiché une grille vide (2026-08-21)."""
    oeuvre_id = await seed_livre(conn)

    rows, total = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book"), ids=[oeuvre_id])

    assert total == 1
    assert rows[0]["id"] == oeuvre_id


async def test_la_grille_ne_montre_que_la_langue_lisible(
    conn: psycopg.AsyncConnection,
) -> None:
    """« Sur Français, des livres français ou traduits en français. » L'œuvre
    seedée est écrite en espagnol et traduite en français : elle se lit en
    fr et en es, pas en arabe — la grille arabe ne la montre pas."""
    await seed_livre(conn)

    _, total_fr = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book"))
    _, total_es = await fetch_cards(conn, CardQuery(lang="es-ES", media="book"))
    _, total_ar = await fetch_cards(conn, CardQuery(lang="ar-SA", media="book"))

    assert (total_fr, total_es, total_ar) == (1, 1, 0)


async def test_le_document_es_porte_les_langues_lisibles(
    conn: psycopg.AsyncConnection,
) -> None:
    from psycopg.rows import dict_row

    from fiv_admin.media import MEDIA
    from fiv_admin.search import construire_doc, parametres_extraction, requete_extraction

    await seed_livre(conn)
    media = MEDIA["book"]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(requete_extraction(media), parametres_extraction(media))
        rows = await cur.fetchall()
    doc = construire_doc(rows[0], media.univers)
    assert sorted(doc["langues"]) == ["es", "fr"]


def test_le_filtre_de_langue_entre_dans_le_corps_es() -> None:
    from fiv_admin.search import corps_liste, corps_recherche

    corps = corps_liste([("air_date", True)], tiebreak_descendant=True, langue="fr", taille=24)
    assert {"term": {"langues": "fr"}} in corps["query"]["bool"]["filter"]
    corps = corps_recherche("macondo", langue="ar", taille=24)
    # La recherche enveloppe son bool dans un function_score (note bayésienne).
    filtres = corps["query"]["function_score"]["query"]["bool"]["filter"]
    assert {"term": {"langues": "ar"}} in filtres
    corps = corps_liste([("air_date", True)], tiebreak_descendant=True, taille=24)
    assert not any("langues" in f.get("term", {}) for f in corps["query"]["bool"]["filter"]), (
        "sans langue, pas de clause — les séries et films ne filtrent jamais là-dessus"
    )


async def test_le_bandeau_de_projection_voit_les_livres(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le bouton « rafraîchir la projection » ne sert que si `cards_state`
    sait compter les livres : leur fiche est le lookup Wikidata du crawler
    (source wikidata, kind lookup_book), pas un brut TMDB."""
    from fiv_admin.catalog import cards_state

    oeuvre_id = await seed_livre(conn)
    # Le brut du crawler — la fiche d'identité du livre (R1).
    await conn.execute(
        """
        insert into raw_source (source, kind, source_id, http_status,
                                payload, payload_sha256)
        values ('wikidata', 'lookup_book', 'Q189378', 200, '{}'::jsonb, '\\x01'),
               ('wikidata', 'lookup_book', 'Q999999', 200, '{}'::jsonb, '\\x02')
        """
    )

    etat = await cards_state(conn, "book")

    assert etat["projected"] == 1, "seul le livre seedé est projeté"
    assert etat["projectable"] == 2, "deux lookups en brut"
    assert etat["pending"] == 1 and etat["stale"] is True, (
        "le second livre attend un refresh — c'est ce que le bandeau affiche"
    )
    assert oeuvre_id  # le pivot existe, la projection le porte


async def test_le_bouton_construit_l_index_absent(conn: psycopg.AsyncConnection) -> None:
    """Après un `livres purge`, l'index n'existe plus : la synchronisation
    incrémentale n'aurait rien à rattraper et renverrait « lancer search
    reindex » à quelqu'un qui vient de cliquer. Elle le construit.

    Sans ES joignable, le test vérifie la borne — la seule logique qui ne
    dépend pas du réseau.
    """
    from fiv_admin.media import MEDIA
    from fiv_admin.search import REINDEX_AUTO_MAX, Recherche

    await seed_livre(conn)
    recherche = Recherche("")  # pas de client : la borne se teste sans réseau
    assert recherche.synchroniser_tout is not None
    assert REINDEX_AUTO_MAX >= 1000, (
        "la borne doit laisser passer les livres et les séries hors TMDB"
    )
    assert MEDIA["book"].card_view == "livre_card"


async def test_la_popularite_du_livre_est_sa_notoriete_wikipedia(
    conn: psycopg.AsyncConnection,
) -> None:
    """Les livres n'ont pas d'inventaire TMDB d'où tirer une popularité : la
    leur est le nombre de Wikipédias qui portent l'œuvre — celui par lequel le
    crawler les fait déjà entrer. Sans cette colonne, le tri « Popularité » ne
    classait rien et le filtre écartait tout."""
    await seed_livre(conn)

    rows, _ = await fetch_cards(
        conn, CardQuery(lang="fr-FR", media="book", sort="popularity", descending=True)
    )
    assert rows[0]["popularity"] == 99.0

    _, retenus = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book", min_popularity=100))
    assert retenus == 0, "le filtre mord — 99 est sous le plancher demandé"

    _, gardes = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book", min_popularity=50))
    assert gardes == 1


async def test_le_titre_suit_la_langue_demandee(conn: psycopg.AsyncConnection) -> None:
    """Le titre affiché est celui de l'article de la langue demandée quand il
    existe, le libellé sinon — sans inventer. (La grille arabe, elle,
    n'affiche pas ce livre du tout : un article arabe n'est pas une
    traduction arabe — c'est le filtre de langue, testé plus haut.)"""
    oeuvre_id = await seed_livre(conn)
    await conn.execute(
        """
        insert into riche_source (oeuvre_id, source, lang, source_id,
                                  content, facts, resolved_by, fetched_at)
        values (%s, 'wikipedia', 'ar', %s, %s, '{}'::jsonb, 'sitelink', now())
        """,
        (oeuvre_id, "مائة عام من العزلة", "رواية ماكوندو."),
    )

    # La fiche s'ouvre dans toutes les langues — elle ne filtre pas.
    fiche = await fetch_work(conn, oeuvre_id, "ar-SA", "book")
    assert fiche["name"] == "مائة عام من العزلة"
    assert fiche["overview"] == "رواية ماكوندو."

    # Pas d'article espagnol dans le seed : le libellé reste, sans mensonge.
    rows, _ = await fetch_cards(conn, CardQuery(lang="es-ES", media="book"))
    assert rows[0]["name"] == "Cien años de soledad"
    assert rows[0]["overview"] == "Le roman de Macondo.", (
        "le texte retombe sur l'aperçu projeté (préférence fr) — pas de vide"
    )


async def test_les_titres_wikipedia_entrent_dans_l_index(
    conn: psycopg.AsyncConnection,
) -> None:
    """Chercher « Cent ans de solitude » doit trouver le livre : le libellé
    projeté est à préférence anglaise, les titres des autres langues vivent
    dans les articles."""
    from psycopg.rows import dict_row

    from fiv_admin.media import MEDIA
    from fiv_admin.search import construire_doc, parametres_extraction, requete_extraction

    await seed_livre(conn)
    media = MEDIA["book"]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(requete_extraction(media), parametres_extraction(media))
        rows = await cur.fetchall()
    doc = construire_doc(rows[0], media.univers)
    assert "Cent ans de solitude" in doc["titres"]


async def test_les_genres_du_livre_viennent_de_wikidata(
    conn: psycopg.AsyncConnection,
) -> None:
    """Un livre n'a pas de genres TMDB : les siens sont le genre littéraire
    P136 de Wikidata, projeté sous la même forme `[{id, name}]` pour que la
    grille, le filtre et l'index n'aient rien à savoir de la provenance."""
    from fiv_admin.catalog import genres_disponibles

    await seed_livre(conn)

    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", media="book"))
    assert rows[0]["genres"] == ["réalisme magique"], (
        "le genre sans libellé est écarté : un genre n'existe que par son nom"
    )

    facettes = await genres_disponibles(conn, "book")
    assert ("réalisme magique", 1) in [(g["name"], g["count"]) for g in facettes]

    _, retenus = await fetch_cards(
        conn, CardQuery(lang="fr-FR", media="book", genres=("réalisme magique",))
    )
    assert retenus == 1


async def test_le_graphe_prefixe_les_genres_de_livre_en_wd(
    conn: psycopg.AsyncConnection,
) -> None:
    """Les genres d'un livre viennent de Wikidata, ceux d'une série de TMDB :
    deux numérotations qui ne doivent jamais se rencontrer dans le graphe."""
    from psycopg.rows import dict_row

    from fiv_admin.graphe import construire_oeuvre, parametres_extraction, requete_extraction
    from fiv_admin.media import MEDIA

    await seed_livre(conn)
    media = MEDIA["book"]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(requete_extraction(media), parametres_extraction(media))
        rows = await cur.fetchall()

    noeud = construire_oeuvre(rows[0], media.univers)
    assert noeud["genres"] == [{"cle": "wd:Q193606", "nom": "réalisme magique"}]
