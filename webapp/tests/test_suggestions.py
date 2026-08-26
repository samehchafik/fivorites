"""Le moteur de suggestions : l'ordre, la dédup, le plafond de distance.

Le graphe est simulé — ces tests vérifient la POLITIQUE du moteur (voisins
d'abord, complément par distance croissante, rien en double, rien au-delà du
plafond), pas le Cypher, qui ne se teste que contre un vrai Neo4j.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from fiv_webapp.cartes import Carte
from fiv_webapp.suggestions import (
    DISTANCE_MAX,
    Affinites,
    Moteur,
    Suggestions,
    distance_depuis_score,
)
from fiv_webapp.univers import UNIVERS


def score_de_distance(distance: float) -> float:
    """L'inverse de `distance_depuis_score` — pour écrire les fixtures dans
    l'unité qu'on raisonne, la distance en points de note."""
    return 1.0 / (1.0 + distance * distance)


class FauxGraphe:
    """Rend des lignes préparées selon la requête reçue : le voisinage, les
    citations des voisins, ou les proches vectoriels."""

    def __init__(
        self,
        voisins: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        proches: list[dict[str, Any]],
    ) -> None:
        self._voisins = voisins
        self._citations = citations
        self._proches = proches
        self.parametres_vus: list[dict[str, Any]] = []

    async def executer(self, cypher: str, **parametres: Any) -> list[dict[str, Any]]:
        self.parametres_vus.append({"cypher": cypher, **parametres})
        if "queryNodes" in cypher:
            return self._proches[: parametres["limite"]]
        if "count(DISTINCT s)" in cypher:
            return self._voisins
        return self._citations[: parametres["limite"]]


def citation(oeuvre_id: int, voisins: int, force: float) -> dict[str, Any]:
    return {
        "oeuvreId": oeuvre_id,
        "titre": f"Œuvre {oeuvre_id}",
        "annee": 2020,
        "affiche": None,
        "univers": "series",
        "voisins": voisins,
        "force": force,
    }


def proche(oeuvre_id: int, distance: float) -> dict[str, Any]:
    return {
        "oeuvreId": oeuvre_id,
        "titre": f"Œuvre {oeuvre_id}",
        "annee": 2020,
        "affiche": None,
        "univers": "series",
        "score": score_de_distance(distance),
    }


def test_distance_depuis_score() -> None:
    # 1/(1+d²) avec d=2 → 0.2 ; et l'aller-retour est exact.
    assert distance_depuis_score(0.2) == pytest.approx(2.0)
    assert distance_depuis_score(1.0) == pytest.approx(0.0)
    assert distance_depuis_score(0.0) == math.inf


async def test_voisins_d_abord_puis_distance() -> None:
    graphe = FauxGraphe(
        voisins=[{"membreId": 7, "communes": 3}],
        citations=[citation(101, voisins=5, force=4.0), citation(102, voisins=2, force=3.0)],
        proches=[proche(201, 0.5), proche(202, 1.1)],
    )
    moteur = Suggestions(graphe)  # type: ignore[arg-type]
    retenues = await moteur.pour(aimes=[1], exclues=[1], univers_interne="series", limite=10)

    # L'ordre est la promesse : la communauté avant l'empreinte.
    assert [s.oeuvre_id for s in retenues] == [101, 102, 201, 202]
    assert [s.source for s in retenues] == ["voisins", "voisins", "proche", "proche"]
    assert retenues[2].distance == pytest.approx(0.5)


async def test_dedup_et_exclusions() -> None:
    graphe = FauxGraphe(
        voisins=[{"membreId": 7, "communes": 1}],
        # 101 sort deux fois (voisins ET proche), 1 est la graine exclue.
        citations=[citation(101, voisins=3, force=4.0)],
        proches=[proche(101, 0.3), proche(1, 0.1), proche(202, 0.8)],
    )
    moteur = Suggestions(graphe)  # type: ignore[arg-type]
    retenues = await moteur.pour(aimes=[1], exclues=[1], univers_interne="series", limite=10)

    assert [s.oeuvre_id for s in retenues] == [101, 202]
    # 101 garde sa raison communautaire — la première voix l'emporte.
    assert retenues[0].source == "voisins"


async def test_plafond_de_distance() -> None:
    graphe = FauxGraphe(
        voisins=[],
        citations=[],
        proches=[proche(201, DISTANCE_MAX - 0.1), proche(202, DISTANCE_MAX + 0.1)],
    )
    moteur = Suggestions(graphe)  # type: ignore[arg-type]
    retenues = await moteur.pour(aimes=[1], exclues=[1], univers_interne="series", limite=10)

    # Au-delà du plafond, la liste préfère rester courte.
    assert [s.oeuvre_id for s in retenues] == [201]


async def test_sans_aime_rien() -> None:
    graphe = FauxGraphe(voisins=[], citations=[], proches=[])
    moteur = Suggestions(graphe)  # type: ignore[arg-type]
    assert await moteur.pour(aimes=[], exclues=[], univers_interne="series") == []
    # Et surtout : aucun appel au graphe — pas de requête pour rien.
    assert graphe.parametres_vus == []


# ---------------------------------------------------------------------------
# Le troisième étage, et l'orchestration des trois
# ---------------------------------------------------------------------------


class FauxRecherche:
    """Un Elasticsearch simulé : les documents des graines, puis les
    affinités. `None` simule une panne ou un index absent."""

    def __init__(
        self,
        documents: list[dict[str, Any]] | None = None,
        affinites: list[int] | None = None,
    ) -> None:
        self._documents = documents
        self._affinites = affinites
        self.demandes: list[dict[str, Any]] = []

    async def documents(self, univers: Any, cles: list[int]) -> list[dict[str, Any]] | None:
        self.demandes.append({"quoi": "documents", "cles": cles})
        return self._documents

    async def affinites(
        self,
        univers: Any,
        *,
        genres: list[str],
        personnes: list[str],
        exclus: list[int],
        taille: int,
    ) -> list[int] | None:
        self.demandes.append(
            {
                "quoi": "affinites",
                "genres": genres,
                "personnes": personnes,
                "exclus": exclus,
                "taille": taille,
            }
        )
        return self._affinites


class FauxCartes:
    """Hydrate en gardant l'ordre reçu — le contrat de `Cartes.hydrater`."""

    def __init__(self, genres_par_id: dict[int, list[str]] | None = None) -> None:
        self._genres = genres_par_id or {}

    async def hydrater(self, conn: Any, univers: Any, ids: list[int]) -> list[Carte]:
        return [
            Carte(
                id=identifiant,
                # Le pivot est décalé de mille : de quoi vérifier que c'est
                # bien lui qui sort dans `oeuvreId`, et la clé dans `id`.
                oeuvre_id=identifiant + 1000,
                univers=univers.slug,
                titre=f"Œuvre {identifiant}",
                titre_original=None,
                annee=2020,
                affiche=None,
                synopsis=None,
                genres=self._genres.get(identifiant, []),
                note=None,
            )
            for identifiant in ids
        ]


class FauxConn:
    """Le pivot d'une œuvre TMDB, lu en base par `Cles` : ici l'identité."""

    def cursor(self) -> Any:
        return self

    async def __aenter__(self) -> FauxConn:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, requete: str, parametres: Any = None) -> None:
        self._pivots = list(parametres["pivots"]) if parametres else []

    async def fetchall(self) -> list[tuple[int, int]]:
        # pivot → clé de vignette : le décalage de mille de FauxCartes,
        # à l'envers.
        return [(pivot, pivot - 1000) for pivot in self._pivots]


async def test_affinites_batissent_la_requete_et_expliquent() -> None:
    """Les genres les plus fréquents d'abord, les exclusions traduites en
    clés de vignette, et les genres partagés nommés pour l'explication."""
    recherche = FauxRecherche(
        documents=[
            {"genres": ["Drame", "Fantastique"], "personnes": ["Emilia Clarke"]},
            {"genres": ["Drame"], "personnes": ["Kit Harington"]},
        ],
        affinites=[42],
    )
    cartes = FauxCartes({42: ["Drame", "Comédie"]})
    moteur = Affinites(recherche, cartes)  # type: ignore[arg-type]

    retenues = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        aimes=[1001],
        exclues=[1001, 1002],
        limite=10,
    )

    demande = recherche.demandes[-1]
    # « Drame » est dans deux graines sur deux : il passe devant.
    assert demande["genres"][0] == "Drame"
    assert "Emilia Clarke" in demande["personnes"]
    # Les exclusions partent en clés de vignette, pas en pivots.
    assert demande["exclus"] == [1, 2]

    assert len(retenues) == 1
    assert retenues[0].source == "affinite"
    assert retenues[0].oeuvre_id == 1042
    assert retenues[0].cle_vignette == 42
    # Seuls les genres réellement partagés sont nommés — « Comédie » n'est
    # pas dans les coups de cœur, elle n'a rien à expliquer.
    assert retenues[0].communs == ["Drame"]


async def test_affinites_sans_index_ne_cassent_rien() -> None:
    """ES absent ou index vide : l'étage rend une liste vide, pas une
    exception — la route doit répondre quand même."""
    moteur = Affinites(FauxRecherche(documents=None), FauxCartes())  # type: ignore[arg-type]
    assert (
        await moteur.pour(
            FauxConn(),  # type: ignore[arg-type]
            UNIVERS["series"],
            aimes=[1001],
            exclues=[1001],
            limite=10,
        )
        == []
    )


async def test_moteur_sans_graphe_repond_par_les_affinites() -> None:
    """LE cas qui a motivé le troisième étage : pas de graphe (ou un graphe
    qui ne connaît pas l'œuvre aimée), et l'onglet répond quand même."""
    recherche = FauxRecherche(documents=[{"genres": ["Drame"], "personnes": []}], affinites=[7])
    moteur = Moteur(recherche, FauxCartes({7: ["Drame"]}), None)  # type: ignore[arg-type]

    retenues, raison = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        aimes=[1001],
        exclues=[1001],
    )
    assert raison is None
    assert [suggestion.source for suggestion in retenues] == ["affinite"]


async def test_moteur_garde_l_ordre_des_etages() -> None:
    """La communauté d'abord, les affinités pour compléter : un signal faible
    ne passe jamais devant un signal fort."""
    graphe = FauxGraphe(
        voisins=[{"membreId": 7, "communes": 2}],
        citations=[citation(101, voisins=4, force=4.0)],
        proches=[],
    )
    recherche = FauxRecherche(documents=[{"genres": ["Drame"], "personnes": []}], affinites=[7])
    moteur = Moteur(recherche, FauxCartes({7: ["Drame"]}), graphe)  # type: ignore[arg-type]

    retenues, raison = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        aimes=[1001],
        exclues=[1001],
    )
    assert raison is None
    assert [suggestion.source for suggestion in retenues] == ["voisins", "affinite"]


async def test_moteur_dit_pourquoi_il_est_vide() -> None:
    """Deux vides, deux raisons : rien d'aimé, ou rien de trouvé. Le front
    n'affiche pas le même message, et surtout pas « panne »."""
    recherche = FauxRecherche(documents=[], affinites=[])
    moteur = Moteur(recherche, FauxCartes(), None)  # type: ignore[arg-type]

    _, sans_graine = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        aimes=[],
        exclues=[],
    )
    assert sans_graine == "aucun_aime"

    _, sans_resultat = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        aimes=[1001],
        exclues=[1001],
    )
    assert sans_resultat == "aucun_resultat"
