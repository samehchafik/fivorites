"""Tests du module de recherche : les parties pures, et le disjoncteur.

Aucun Elasticsearch ici — le transport est simulé. Ce qui se teste : la forme
des documents (le contrat du mapping `strict`), la forme des requêtes, et le
comportement de panne — c'est lui qui garantit que la grille survit à un ES
absent, ce que la production rencontrera forcément un jour.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from conftest import requires_db
from fiv_admin.media import MEDIA
from fiv_admin.search import (
    _IDS_CHANGES,
    FENETRE_MAX,
    TRIS,
    PageIds,
    Recherche,
    _plier,
    alias_de,
    construire_doc,
    corps_liste,
    corps_recherche,
    definition_index,
    parametres_extraction,
    requete_extraction,
)


def _ligne(**champs: Any) -> dict[str, Any]:
    """Une ligne d'extraction : tout à `None` sauf ce que le test regarde."""
    base: dict[str, Any] = dict.fromkeys(
        (
            "id",
            "nom_inventaire",
            "popularity",
            "adult",
            "oeuvre_id",
            "fiche",
            "name",
            "original_name",
            "first_air_date",
            "annee",
            "fetched_at",
            "status",
            "original_language",
            "vote_count",
            "note_bayes",
            "poster_path",
            "has_overview",
            "genres",
            "origin_country",
            "titres",
        )
    )
    base.update(champs)
    return base


class TestConstruireDoc:
    def test_oeuvre_jamais_collectee(self) -> None:
        """Le fond de catalogue n'a que son nom d'inventaire — il doit quand
        même se chercher : c'est tout l'intérêt pour le tableau d'acquisition."""
        doc = construire_doc(_ligne(id=42, nom_inventaire="Camp Lazlo", adult=False), "movies")
        assert doc == {
            "univers": "movies",
            "id_tmdb": 42,
            "titres": ["Camp Lazlo"],
            "titre_principal": ["Camp Lazlo"],
            "original_name": "Camp Lazlo",
            "nom_tri": "camp lazlo",
            "adult": False,
            "fiche": False,
            "has_poster": False,
            "has_overview": False,
        }

    def test_absences_omises(self) -> None:
        """Pas de `null` dans `_source` : une absence n'est pas envoyée."""
        doc = construire_doc(_ligne(id=1, nom_inventaire="X"), "series")
        assert None not in doc.values()
        assert "note_bayes" not in doc
        assert "poster_path" not in doc

    def test_titres_dedupliques_et_dates_serialisees(self) -> None:
        doc = construire_doc(
            _ligne(
                id=1399,
                fiche=True,
                name="Game of Thrones",
                original_name="Game of Thrones",
                nom_inventaire="Game of Thrones",
                titres=["Game of Thrones", "Le Trône de fer"],
                first_air_date=date(2011, 4, 17),
                fetched_at=datetime(2026, 8, 1, 12, 0),
                note_bayes=8.512345,
                poster_path="/p.jpg",
                has_overview=True,
            ),
            "series",
        )
        # Le nom courant est déjà dans les titres du payload : pas de doublon.
        assert doc["titres"] == ["Game of Thrones", "Le Trône de fer"]
        assert doc["first_air_date"] == "2011-04-17"
        assert doc["fetched_at"] == "2026-08-01T12:00:00"
        assert doc["note_bayes"] == 8.51
        assert doc["has_poster"] is True

    def test_personnes_fusionnees(self) -> None:
        """Crédits TMDB et auteurs Wikidata se rejoignent dans `personnes`,
        dédupliqués — c'est le champ qui rend un nom cherchable."""
        doc = construire_doc(
            _ligne(
                id=1,
                nom_inventaire="X",
                personnes=["Emilia Clarke", "Kit Harington"],
                auteurs=["Emilia Clarke", "George R. R. Martin"],
            ),
            "series",
        )
        assert doc["personnes"] == ["Emilia Clarke", "Kit Harington", "George R. R. Martin"]

    def test_conforme_au_mapping_strict(self) -> None:
        """`dynamic: strict` refuse tout champ inconnu : chaque clé produite
        doit exister dans le mapping, sinon la réindexation casse en vol."""
        connus = set(definition_index("series")["mappings"]["properties"])
        doc = construire_doc(
            _ligne(
                id=1,
                nom_inventaire="X",
                fiche=True,
                name="X",
                annee=2020,
                genres=["Drama"],
                origin_country=["FR"],
                vote_count=12,
                note_bayes=7.0,
                popularity=3.2,
                adult=False,
                oeuvre_id=99,
                status="Ended",
                original_language="fr",
            ),
            "series",
        )
        assert set(doc) <= connus


class TestCorpsListe:
    def test_tri_filtres_et_departage(self) -> None:
        corps = corps_liste(
            [("air_date", True), ("popularity", False)],
            tiebreak_descendant=True,
            fiche=True,
            taille=24,
            depuis=24,
        )
        # `missing: _last` = le `nulls last` du SQL ; le départage final sur
        # l'id est celui de `fetch_cards`, même sens.
        assert corps["sort"] == [
            {"first_air_date": {"order": "desc", "missing": "_last"}},
            {"popularity": {"order": "asc", "missing": "_last"}},
            {"id_tmdb": {"order": "desc"}},
        ]
        assert corps["query"] == {"bool": {"filter": [{"term": {"fiche": True}}]}}
        assert corps["from"] == 24
        assert corps["_source"] is False

    def test_tous_les_tris_des_routes_sont_couverts(self) -> None:
        """Chaque tri que les routes acceptent doit avoir son champ ES — et ce
        champ doit exister au mapping, sinon le parcours casse en vol."""
        from fiv_admin.catalog import CARD_SORTS
        from fiv_admin.queries import SORTS

        assert set(CARD_SORTS) <= set(TRIS)
        assert set(SORTS) <= set(TRIS)
        connus = set(definition_index("series")["mappings"]["properties"])
        assert set(TRIS.values()) <= connus

    def test_plier(self) -> None:
        assert _plier("Père Noël") == "pere noel"
        assert _plier("GAME of Thrones") == "game of thrones"


class TestCorpsRecherche:
    def test_texte_simple(self) -> None:
        corps = corps_recherche("trone", taille=24, depuis=0)
        clauses = corps["query"]["function_score"]["query"]["bool"]
        assert clauses["filter"] == []
        # Toutes les langues restent cherchées : c'est ce qui trouve
        # « Le Trône de fer » en tapant son titre français.
        assert {"match": {"titres": {"query": "trone", "operator": "and"}}} in clauses["should"]
        # Les documents ne voyagent pas : ES rend des ids, Postgres hydrate.
        assert corps["_source"] is False

    def test_le_titre_principal_domine_les_traductions(self) -> None:
        """Le classement d'une frappe courte, et la raison d'être du champ.

        Mesuré avant ce boost : « com » rendait « Morangos com Açúcar » et
        « Conversas com um Assassino » — *com* est une préposition portugaise,
        et les ~45 langues vivent dans le même champ. Chercher partout reste
        juste ; c'est le classement qui doit préférer le titre principal.
        """
        clauses = corps_recherche("com", taille=12, depuis=0)["query"]["function_score"]["query"][
            "bool"
        ]["should"]

        def boost(champ: str) -> float:
            for clause in clauses:
                for forme in ("match", "match_phrase"):
                    if forme in clause and champ in clause[forme]:
                        return float(clause[forme][champ].get("boost", 1.0))
            raise AssertionError(f"clause absente : {champ}")

        # La phrase du titre principal au-dessus de tout, ses préfixes
        # ensuite, et les traductions derrière.
        assert boost("titre_principal.exact") > boost("titre_principal")
        assert boost("titre_principal") > boost("titres.exact")
        assert boost("titres.exact") > boost("titres")

    def test_texte_numerique_cherche_aussi_l_id(self) -> None:
        corps = corps_recherche("1399", taille=24, depuis=0)
        devrait = corps["query"]["function_score"]["query"]["bool"]["should"]
        assert {"term": {"id_tmdb": {"value": 1399, "boost": 10.0}}} in devrait

    def test_filtres_de_la_grille(self) -> None:
        corps = corps_recherche(
            "x",
            fiche=True,
            with_poster=True,
            with_overview=True,
            min_popularity=2.5,
            taille=24,
            depuis=48,
        )
        filtres = corps["query"]["function_score"]["query"]["bool"]["filter"]
        assert {"term": {"fiche": True}} in filtres
        assert {"term": {"has_poster": True}} in filtres
        assert {"term": {"has_overview": True}} in filtres
        assert {"range": {"popularity": {"gte": 2.5}}} in filtres
        assert corps["from"] == 48

    def test_genres_en_ou(self) -> None:
        """Plusieurs genres cochés = `terms`, donc un OU. Un ET viderait la
        liste dès le deuxième : la plupart des œuvres n'en portent que deux."""
        corps = corps_recherche("x", genres=["Comédie", "Drame"], taille=10, depuis=0)
        filtres = corps["query"]["function_score"]["query"]["bool"]["filter"]
        assert {"terms": {"genres": ["Comédie", "Drame"]}} in filtres

    def test_genres_vides_ne_filtrent_pas(self) -> None:
        """Aucun genre coché ne doit pas produire un `terms` vide, qui ne
        matcherait rien du tout — la grille se viderait sans raison."""
        for vide in (None, [], ()):
            corps = corps_liste(
                [("air_date", True)], tiebreak_descendant=True, genres=vide, taille=10
            )
            assert corps["query"]["bool"]["filter"] == []

    def test_personnes_et_genres_cherchables(self) -> None:
        """La frappe passe aussi par les gens et par les genres : un acteur
        tapé rend sa filmographie, « policier » rend les Crime — jamais devant
        un titre exact (boosts : 3 > 1,5 > 1)."""
        devrait = corps_recherche("spielberg", taille=10, depuis=0)["query"]["function_score"][
            "query"
        ]["bool"]["should"]
        assert {
            "match": {"personnes": {"query": "spielberg", "operator": "and", "boost": 1.5}}
        } in devrait
        assert {"match": {"genres.texte": {"query": "spielberg", "operator": "and"}}} in devrait

    def test_synonymes_de_genres_a_la_requete(self) -> None:
        """Les synonymes vivent dans l'analyseur de RECHERCHE : enrichir le
        vocabulaire ne demande pas de réindexer. Et « policier » doit bien y
        mener à Crime — c'est le cas d'usage qui a créé le champ."""
        analyse = definition_index("series")["settings"]["analysis"]
        assert any(
            "policier" in ligne and "crime" in ligne
            for ligne in analyse["filter"]["genres_synonymes"]["synonyms"]
        )
        assert "genres_synonymes" in analyse["analyzer"]["genres_recherche"]["filter"]
        # L'analyseur d'INDEX des genres, lui, reste sans synonymes.
        assert "genres_synonymes" not in analyse["analyzer"]["titres_index"]["filter"]

    def test_le_classement_ignore_la_popularite(self) -> None:
        """Le biais occidental de `popularity` (dictionnaire de données, §4)
        ne doit pas entrer dans la pertinence — la note bayésienne, si."""
        corps = json.dumps(corps_recherche("x", taille=10, depuis=0))
        assert "note_bayes" in corps
        assert '"field": "popularity"' not in corps


def _client_simule(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://es.test")


class TestRecherche:
    async def test_url_vide_desactive(self) -> None:
        recherche = Recherche("")
        assert not recherche.active
        page = await recherche.page_cards(MEDIA["tv"], "x", page=1, page_size=24)
        assert page is None

    async def test_page_normale(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == f"/{alias_de(MEDIA['tv'])}/_search"
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "total": {"value": 2, "relation": "eq"},
                        "hits": [{"_id": "1399"}, {"_id": "94997"}],
                    }
                },
            )

        recherche = Recherche("http://es.test")
        recherche._client = _client_simule(handler)
        page = await recherche.page_cards(MEDIA["tv"], "trone", page=1, page_size=24)
        assert page == PageIds(ids=[1399, 94997], total=2)

    async def test_panne_ouvre_le_disjoncteur(self) -> None:
        appels = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal appels
            appels += 1
            raise httpx.ConnectError("connexion refusée")

        recherche = Recherche("http://es.test")
        recherche._client = _client_simule(handler)

        assert await recherche.page_cards(MEDIA["tv"], "x", page=1, page_size=24) is None
        # Coupé : la frappe suivante ne paie même pas une tentative.
        assert not recherche.active
        assert await recherche.page_cards(MEDIA["tv"], "x", page=1, page_size=24) is None
        assert appels == 1

    async def test_pagination_hors_fenetre_reste_au_sql(self) -> None:
        """Au-delà de la fenêtre d'ES, on décline sans appel réseau — et sans
        ouvrir le disjoncteur : ce n'est pas une panne."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("aucun appel attendu")

        recherche = Recherche("http://es.test")
        recherche._client = _client_simule(handler)
        page = await recherche.page_cards(
            MEDIA["tv"], "x", page=FENETRE_MAX // 24 + 2, page_size=24
        )
        assert page is None
        assert recherche.active

    async def test_acquisition_plafonne_le_total(self) -> None:
        """Le total annoncé ne dépasse jamais les ids réellement rendus : la
        pagination ne doit pas promettre des pages introuvables."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "total": {"value": 125_000, "relation": "eq"},
                        "hits": [{"_id": str(i)} for i in range(3)],
                    }
                },
            )

        recherche = Recherche("http://es.test")
        recherche._client = _client_simule(handler)
        page = await recherche.ids_acquisition(MEDIA["movie"], "the")
        assert page == PageIds(ids=[0, 1, 2], total=3)


# Un payload TMDB réduit à ce que l'extraction des titres regarde — plus les
# champs que la projection de vignettes projette.
PAYLOAD_1399 = {
    "name": "Le Trône de fer",
    "original_name": "Game of Thrones",
    "overview": "Neuf familles nobles se disputent le contrôle de Westeros.",
    "poster_path": "/got.jpg",
    "first_air_date": "2011-04-17",
    "vote_average": 8.4,
    "vote_count": 22000,
    "status": "Ended",
    "original_language": "en",
    "origin_country": ["US"],
    "genres": [{"id": 1, "name": "Drame"}],
    # Les crédits, réduits à ce que l'extraction des personnes regarde : la
    # distribution consolidée, le département Directing, les créateurs.
    "aggregate_credits": {
        "cast": [{"name": "Emilia Clarke"}, {"name": "Kit Harington"}],
        "crew": [
            {"name": "Alan Taylor", "department": "Directing"},
            {"name": "Ramin Djawadi", "department": "Sound"},
        ],
    },
    "created_by": [{"name": "David Benioff"}],
    "alternative_titles": {"results": [{"iso_3166_1": "ES", "title": "Juego de tronos"}]},
    "translations": {
        "translations": [
            # La variante régionale : un titre différent de la racine.
            {"iso_639_1": "fr", "iso_3166_1": "CA", "data": {"name": "Le trône de fer"}},
            {"iso_639_1": "ru", "iso_3166_1": "RU", "data": {"name": "Игра престолов"}},
            # Un `name` vide veut dire « pas de version localisée » : exclu.
            {"iso_639_1": "en", "iso_3166_1": "US", "data": {"name": ""}},
            # Identique à l'original : dédupliqué, pas répété.
            {"iso_639_1": "de", "iso_3166_1": "DE", "data": {"name": "Game of Thrones"}},
        ]
    },
}


@pytest.mark.integration
@requires_db
class TestExtraction:
    """La requête d'extraction, contre une vraie base : les chemins jsonb ne
    se vérifient pas sur une maquette."""

    async def _extraire(self, conn: psycopg.AsyncConnection) -> dict[int, dict[str, Any]]:
        media = MEDIA["tv"]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(requete_extraction(media), parametres_extraction(media))
            return {row["id"]: row for row in await cur.fetchall()}

    async def test_titres_toutes_langues(self, conn: psycopg.AsyncConnection) -> None:
        from fiv_admin.catalog import refresh_cards

        await conn.execute(
            """
            insert into tmdb_catalog (id, original_name, popularity, exported_on) values
                (1399, 'Game of Thrones', 400.0, date '2026-08-05'),
                (4000, 'Jamais collectée',  0.1, date '2026-08-05')
            """
        )
        await conn.execute("insert into oeuvre (univers, id_tmdb) values ('series', 1399)")
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', '1399', 'fr-FR', 200, %s::jsonb, %s)
            """,
            (json.dumps(PAYLOAD_1399), b"\x01"),
        )
        await refresh_cards(conn)

        lignes = await self._extraire(conn)
        assert set(lignes) == {1399, 4000}

        got = lignes[1399]
        # Tous les titres, dédupliqués, sans les vides : c'est LE gain de
        # l'index — « Le trône de fer » devient trouvable.
        assert sorted(got["titres"]) == [
            "Game of Thrones",
            "Juego de tronos",
            "Le Trône de fer",
            "Le trône de fer",
            "Игра престолов",
        ]
        assert got["fiche"] is True
        assert got["oeuvre_id"] is not None
        assert got["genres"] == ["Drame"]
        # (8,4 × 22 000 + 6,5 × 50) / 22 050 : la formule de la grille.
        assert float(got["note_bayes"]) == pytest.approx(8.396, abs=0.001)

        # Les gens : la distribution et le créateur entrent, le compositeur
        # (département Sound) reste dehors — seul Directing passe le chemin.
        assert sorted(got["personnes"]) == [
            "Alan Taylor",
            "David Benioff",
            "Emilia Clarke",
            "Kit Harington",
        ]

        doc = construire_doc(got, "series")
        assert doc["fiche"] is True
        assert doc["has_poster"] is True
        assert "Le trône de fer" in doc["titres"]
        assert "Emilia Clarke" in doc["personnes"]

        jamais = lignes[4000]
        assert jamais["titres"] is None
        assert jamais["fiche"] is False
        doc = construire_doc(jamais, "series")
        assert doc["titres"] == ["Jamais collectée"]

    async def test_extraction_restreinte_aux_ids(self, conn: psycopg.AsyncConnection) -> None:
        """`ids` non nul = la synchronisation : seules les œuvres listées
        sortent, le reste de l'univers n'est pas relu."""
        await conn.execute(
            """
            insert into tmdb_catalog (id, original_name, popularity, exported_on) values
                (1399, 'Game of Thrones', 400.0, date '2026-08-05'),
                (4000, 'Jamais collectée',  0.1, date '2026-08-05')
            """
        )
        media = MEDIA["tv"]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(requete_extraction(media), parametres_extraction(media, [1399]))
            lignes = await cur.fetchall()
        assert [ligne["id"] for ligne in lignes] == [1399]

    async def test_ids_changes_depuis_le_marqueur(self, conn: psycopg.AsyncConnection) -> None:
        """Le filet de la synchronisation : une collecte (`fetch_state`) ou une
        entrée d'inventaire nouvelle réapparaissent, le reste dort."""
        await conn.execute(
            """
            insert into tmdb_catalog (id, original_name, popularity, exported_on) values
                (1399, 'Game of Thrones', 400.0, date '2026-08-05')
            """
        )
        async with conn.cursor() as cur:
            await cur.execute("select now()")
            depuis = (await cur.fetchone())[0].isoformat()

            params = {
                "source": "tmdb",
                "kind": "tv",
                "univers": "series",
                "depuis": depuis,
            }
            await cur.execute(_IDS_CHANGES, params)
            assert await cur.fetchall() == [], "rien n'a bougé depuis le marqueur"

            # Une passe de collecte touche la fiche…
            await cur.execute(
                """
                insert into fetch_state (source, kind, source_id, last_fetched_at,
                                         last_success_at, last_status)
                values ('tmdb', 'tv', '1399', now(), now(), 200)
                """
            )
            # …et l'export du jour apporte une nouveauté.
            await cur.execute(
                """
                insert into tmdb_catalog (id, original_name, popularity, exported_on)
                values (5000, 'Toute nouvelle', 1.0, current_date)
                """
            )
            await cur.execute(_IDS_CHANGES, params)
            assert sorted(row[0] for row in await cur.fetchall()) == [1399, 5000]

    async def test_filtre_genres_sql_et_facettes(self, conn: psycopg.AsyncConnection) -> None:
        """Le repli SQL du filtre par genre, et la liste qui peuple la case à
        cocher. Les libellés sont ceux du payload, donc en français."""
        from fiv_admin.catalog import CardQuery, fetch_cards, genres_disponibles, refresh_cards

        for id_tmdb, nom, genres in (
            (1, "Une comédie", ["Comédie"]),
            (2, "Un drame", ["Drame"]),
            (3, "Les deux", ["Comédie", "Drame"]),
        ):
            await conn.execute(
                """
                insert into raw_source (source, kind, source_id, lang, http_status,
                                        payload, payload_sha256)
                values ('tmdb', 'tv', %s, 'fr-FR', 200, %s::jsonb, %s)
                """,
                (
                    str(id_tmdb),
                    json.dumps(
                        {
                            "name": nom,
                            "genres": [{"id": i, "name": g} for i, g in enumerate(genres)],
                        }
                    ),
                    bytes([id_tmdb]),
                ),
            )
        await refresh_cards(conn)

        facettes = await genres_disponibles(conn, "tv")
        assert {f["name"]: f["count"] for f in facettes} == {"Comédie": 2, "Drame": 2}

        async def ids(*genres: str) -> list[int]:
            rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", genres=genres))
            return sorted(row["id"] for row in rows)

        assert await ids("Comédie") == [1, 3]
        assert await ids("Drame") == [2, 3]
        # Un OU, pas un ET : l'union, pas l'intersection.
        assert await ids("Comédie", "Drame") == [1, 2, 3]
        # Aucun genre = aucun filtre, et surtout pas une liste vide.
        assert await ids() == [1, 2, 3]
        # Le filtre est exact : pas de repli sans accent.
        assert await ids("Comedie") == []

    async def test_fiche_hors_inventaire(self, conn: psycopg.AsyncConnection) -> None:
        """Une œuvre projetée sans ligne d'inventaire — import manuel, export
        partiel — doit entrer dans l'index : la grille la montre."""
        from fiv_admin.catalog import refresh_cards

        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', '777', 'fr-FR', 200, %s::jsonb, %s)
            """,
            (json.dumps({"name": "Hors inventaire", "original_name": "Off Catalog"}), b"\x02"),
        )
        await refresh_cards(conn)

        lignes = await self._extraire(conn)
        assert 777 in lignes
        assert lignes[777]["fiche"] is True
        doc = construire_doc(lignes[777], "series")
        assert "Hors inventaire" in doc["titres"]
