"""Les routes publiques répondent — le contrôle qui manquait.

**Pourquoi ce fichier existe.** Un 500 est parti en production sur
`/api/public/recherche` : un paramètre renommé, une ligne du corps restée sur
l'ancien nom, et ce nom se résolvait vers la FONCTION de route homonyme
définie plus bas dans le module. Ruff ne pouvait rien y voir — le nom
existait — les tests unitaires ne touchaient pas les routes, et le lot est
passé.

Ces tests appellent donc les routes, avec des dépendances substituées : ni
Postgres, ni Elasticsearch, ni Neo4j. Ils ne vérifient pas la pertinence
(c'est le travail des tests de moteur) mais le contrat de surface — le code
s'exécute, la forme est celle annoncée — et c'est exactement ce qui a manqué.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from fiv_webapp.app import create_app
from fiv_webapp.cartes import Carte
from fiv_webapp.config import Settings
from fiv_webapp.deps import (
    obtenir_cartes,
    obtenir_conn,
    obtenir_fiches,
    obtenir_recherche,
    obtenir_signaux,
    session_optionnelle,
)
from fiv_webapp.fiche import Fiche
from fiv_webapp.recherche import Facette, PageIds


class RechercheMuette:
    """Un Elasticsearch qui ne répond pas : c'est le cas le plus dur, celui du
    repli SQL — et il doit répondre 200."""

    async def page(self, *args: Any, **kwargs: Any) -> PageIds | None:
        return None

    async def facettes(self, *args: Any, **kwargs: Any) -> dict[str, list[Facette]] | None:
        return {"genres": [Facette(valeur="Drame", nombre=3)]}

    async def documents(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def affinites(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def titres(self, *args: Any, **kwargs: Any) -> dict[int, str]:
        # Index muet : aucun titre localisé, et la route doit garder ceux de
        # la projection plutôt que de vider la liste.
        return {}


class CartesFeintes:
    async def chercher_sql(self, *args: Any, **kwargs: Any) -> list[int]:
        return [42]

    async def hydrater(self, conn: Any, univers: Any, ids: list[int]) -> list[Carte]:
        return [
            Carte(
                id=identifiant,
                oeuvre_id=identifiant + 1000,
                univers=univers.slug,
                titre="Une œuvre",
                titre_original=None,
                annee=2020,
                affiche=None,
                synopsis=None,
                genres=["Drame"],
                note=7.5,
            )
            for identifiant in ids
        ]


class FichesFeintes:
    async def pour(self, conn: Any, univers: Any, identifiant: int, **kwargs: Any) -> Fiche:
        return Fiche(
            id=identifiant,
            oeuvre_id=identifiant + 1000,
            univers=univers.slug,
            titre="Une œuvre",
            titre_original=None,
        )


class SignauxFeints:
    async def session_existe(self, conn: Any, session_id: str) -> bool:
        return False

    async def pivots(self, conn: Any, session_id: str) -> dict[str, list[int]]:
        return {"aime": [], "aime_pas": [], "a_voir": []}

    async def lister(self, conn: Any, session_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": 42,
                "oeuvreId": 1042,
                "univers": "series",
                "statut": "aime",
                "titre": "Une œuvre",
                "affiche": None,
                "annee": 2020,
            }
        ]


@pytest.fixture
def client() -> TestClient:
    """L'application, sans base ni index — le lifespan n'est pas déclenché :
    `TestClient` sans `with` ne l'exécute pas, et c'est ce qu'on veut."""
    app = create_app(Settings(secret_key="pour-les-tests"))
    app.dependency_overrides[obtenir_conn] = lambda: None
    app.dependency_overrides[obtenir_recherche] = RechercheMuette
    app.dependency_overrides[obtenir_cartes] = CartesFeintes
    app.dependency_overrides[obtenir_fiches] = FichesFeintes
    app.dependency_overrides[obtenir_signaux] = SignauxFeints
    return TestClient(app)


class TestRecherche:
    def test_frappe_simple(self, client: TestClient) -> None:
        reponse = client.get("/api/public/recherche", params={"univers": "series", "q": "lucif"})
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["moteur"] == "sql"
        assert corps["items"][0]["titre"] == "Une œuvre"

    def test_la_forme_exacte_du_500(self, client: TestClient) -> None:
        """L'URL qui a cassé la production, mot pour mot."""
        reponse = client.get(
            "/api/public/recherche",
            params={"univers": "series", "q": "lucif", "langue": "fr"},
        )
        assert reponse.status_code == 200

    def test_filtres_de_toutes_dimensions(self, client: TestClient) -> None:
        reponse = client.get(
            "/api/public/recherche",
            params=[
                ("univers", "series"),
                ("q", "lucif"),
                ("genres", "Drame"),
                ("genres", "Comédie"),
                ("plateformes", "Netflix"),
                ("langue", "ar"),
                ("page", "2"),
            ],
        )
        assert reponse.status_code == 200
        assert reponse.json()["langue"] == "ar"

    def test_une_dimension_que_l_univers_ne_porte_pas_est_ignoree(self, client: TestClient) -> None:
        """Un livre ne se regarde pas sur Netflix : le filtre est ignoré, pas
        refusé — la liste des dimensions est un contrat que le client
        découvre, et elle bougera."""
        reponse = client.get(
            "/api/public/recherche",
            params={"univers": "livres", "q": "an", "plateformes": "Netflix"},
        )
        assert reponse.status_code == 200

    def test_univers_inconnu(self, client: TestClient) -> None:
        reponse = client.get("/api/public/recherche", params={"univers": "bd", "q": "x"})
        assert reponse.status_code == 400
        assert "attendu" in reponse.json()["detail"]


class TestFiltres:
    def test_groupes_par_univers(self, client: TestClient) -> None:
        series = client.get("/api/public/filtres", params={"univers": "series"}).json()
        livres = client.get("/api/public/filtres", params={"univers": "livres"}).json()
        assert [g["champ"] for g in series["groupes"]] == ["genres", "plateformes"]
        # Un livre ne se regarde pas sur Netflix.
        assert [g["champ"] for g in livres["groupes"]] == ["genres"]


class TestFiche:
    def test_fiche_et_langue(self, client: TestClient) -> None:
        reponse = client.get("/api/public/fiche/1399", params={"univers": "series", "langue": "es"})
        assert reponse.status_code == 200
        corps = reponse.json()
        # Les clés que le front lit, toutes présentes même vides.
        for cle in ("offres", "lienOffres", "paysOffres", "videos", "saisons"):
            assert cle in corps

    def test_saison_refusee_hors_series(self, client: TestClient) -> None:
        reponse = client.get("/api/public/fiche/32/saison/1", params={"univers": "livres"})
        assert reponse.status_code == 400


class TestSante:
    def test_health(self, client: TestClient) -> None:
        assert client.get("/api/public/health").json() == {"status": "ok"}


class TestMaListe:
    """L'onglet « Ma liste » relit `/signaux`. Sans session, la réponse est une
    liste vide — jamais une erreur : quelqu'un qui n'a rien classé n'est pas
    dans un cas d'exception, il est au début."""

    def test_sans_session_liste_vide(self, client: TestClient) -> None:
        reponse = client.get("/api/public/signaux?langue=fr")
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["items"] == []
        assert corps["langue"] == "fr"

    def test_langue_inconnue_retombe_sur_le_francais(self, client: TestClient) -> None:
        assert client.get("/api/public/signaux?langue=pt").json()["langue"] == "fr"

    def test_statut_inconnu_refuse(self, client: TestClient) -> None:
        assert client.get("/api/public/signaux?statut=peut-etre").status_code == 400


class TestSuggestions:
    """La route /suggestions — le CONTRAT entre la route et le moteur.

    Ces tests existent à cause d'un 500 en production : le moteur s'était mis
    à rendre trois valeurs, la route en dépaquetait deux — et rien ne
    l'attrapait, parce que les tests du moteur l'appellent en direct et
    qu'aucun test n'appelait la route. Le dépaquetage est un contrat, et un
    contrat se teste là où il se noue.
    """

    def test_sans_session_la_reponse_est_complete(self, client: TestClient) -> None:
        reponse = client.get("/api/public/suggestions?univers=series")
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["raison"] == "aucune_session"
        assert corps["total"] == 0 and corps["encore"] is False and corps["page"] == 1

    def test_avec_session_la_route_depaquette_le_moteur(self, client: TestClient) -> None:
        """Le chemin qui a cassé : session valide → la route appelle le moteur
        réel et dépaquette sa réponse. Graines vides → aucun_aime, mais le
        DÉPAQUETAGE est exercé — c'est lui qui a rendu un 500."""
        client.app.dependency_overrides[session_optionnelle] = lambda: "session-de-test"
        try:
            reponse = client.get(
                "/api/public/suggestions?univers=series&sans=Animation&sur=Netflix&langue=fr&page=2"
            )
            assert reponse.status_code == 200
            corps = reponse.json()
            assert corps["raison"] == "aucun_aime"
            assert corps["page"] == 2
        finally:
            client.app.dependency_overrides.pop(session_optionnelle, None)
