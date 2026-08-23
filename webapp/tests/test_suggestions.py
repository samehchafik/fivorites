"""Le moteur de suggestions : l'ordre, la dédup, le plafond de distance.

Le graphe est simulé — ces tests vérifient la POLITIQUE du moteur (voisins
d'abord, complément par distance croissante, rien en double, rien au-delà du
plafond), pas le Cypher, qui ne se teste que contre un vrai Neo4j.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from fiv_webapp.suggestions import DISTANCE_MAX, Suggestions, distance_depuis_score


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
