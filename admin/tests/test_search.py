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
    FENETRE_MAX,
    PageIds,
    Recherche,
    alias_de,
    construire_doc,
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
            "original_name": "Camp Lazlo",
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


class TestCorpsRecherche:
    def test_texte_simple(self) -> None:
        corps = corps_recherche("trone", taille=24, depuis=0)
        clauses = corps["query"]["function_score"]["query"]["bool"]
        assert clauses["filter"] == []
        assert clauses["should"][0] == {"match": {"titres": {"query": "trone", "operator": "and"}}}
        # Les documents ne voyagent pas : ES rend des ids, Postgres hydrate.
        assert corps["_source"] is False

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

        doc = construire_doc(got, "series")
        assert doc["fiche"] is True
        assert doc["has_poster"] is True
        assert "Le trône de fer" in doc["titres"]

        jamais = lignes[4000]
        assert jamais["titres"] is None
        assert jamais["fiche"] is False
        doc = construire_doc(jamais, "series")
        assert doc["titres"] == ["Jamais collectée"]

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
