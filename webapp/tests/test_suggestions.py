"""Le moteur de suggestions : la pondération, la fusion, la corroboration.

Sources simulées — ces tests vérifient la POLITIQUE du moteur, pas le Cypher
ni le corps ES, qui ne se testent que contre un vrai service :

* les graines sont pondérées par ce qu'elles disent (un verdict pèse plus
  qu'une intention) ;
* aucune source ne plafonne les autres — c'était le défaut de la cascade,
  dont le premier étage (la communauté, arrêtée en 2019) occupait toute la
  liste ;
* deux savoirs indépendants qui désignent la même œuvre l'emportent sur un
  seul, même très confiant.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from fiv_webapp.cartes import Carte
from fiv_webapp.suggestions import (
    APPORT_COMMUNAUTE,
    APPORT_EMPREINTE,
    DISTANCE_MAX,
    MULTIPLICATEUR_CORROBORATION,
    POIDS_STATUT,
    Candidat,
    Moteur,
    Suggestion,
    distance_depuis_score,
)
from fiv_webapp.univers import UNIVERS


def score_de_distance(distance: float) -> float:
    """L'inverse de `distance_depuis_score` — pour écrire les fixtures dans
    l'unité qu'on raisonne, la distance en points de note."""
    return 1.0 / (1.0 + distance * distance)


# ---------------------------------------------------------------------------
# Les briques
# ---------------------------------------------------------------------------


def test_distance_depuis_score() -> None:
    # 1/(1+d²) avec d=2 → 0.2 ; et l'aller-retour est exact.
    assert distance_depuis_score(0.2) == pytest.approx(2.0)
    assert distance_depuis_score(1.0) == pytest.approx(0.0)
    assert distance_depuis_score(0.0) == math.inf


class TestCandidat:
    def test_le_plus_fort_apport_gagne(self) -> None:
        """Une source qui parle deux fois de la même œuvre ne cumule pas :
        deux graines vaguement proches ne doivent pas battre une graine très
        proche, sinon un profil large écrase un profil précis."""
        candidat = Candidat(oeuvre_id=1)
        candidat.verser("proche", 0.3)
        candidat.verser("proche", 0.9)
        candidat.verser("proche", 0.5)
        assert candidat.apports["proche"] == 0.9
        assert candidat.score == pytest.approx(0.9)

    def test_corroboration_multiplie(self) -> None:
        """Le geste demandé : contenu ET communauté d'accord → total multiplié."""
        seul = Candidat(oeuvre_id=1)
        seul.verser("proche", 0.5)
        assert not seul.corrobore

        accord = Candidat(oeuvre_id=2)
        accord.verser("proche", 0.5)
        accord.verser("voisins", 0.5)
        assert accord.corrobore
        assert accord.score == pytest.approx(1.0 * MULTIPLICATEUR_CORROBORATION)

    def test_deux_sources_de_contenu_ne_corroborent_pas(self) -> None:
        """L'empreinte et les affinités regardent la même matière : leur
        accord n'est pas une confirmation indépendante."""
        candidat = Candidat(oeuvre_id=1)
        candidat.verser("proche", 0.4)
        candidat.verser("affinite", 0.4)
        assert not candidat.corrobore

    def test_source_dominante(self) -> None:
        candidat = Candidat(oeuvre_id=1)
        candidat.verser("affinite", 0.2)
        candidat.verser("voisins", 0.7)
        assert candidat.source_dominante == "voisins"
        assert Suggestion.depuis(candidat).source == "voisins"


class TestGraines:
    def test_ponderees_par_statut(self) -> None:
        """« Vu et aimé » est un verdict, « je veux voir » une intention —
        et `aime_pas` ne décrit pas un goût à poursuivre."""
        moteur = Moteur(None, None, None)  # type: ignore[arg-type]
        graines = moteur.graines({"aime": [1, 2], "a_voir": [3], "aime_pas": [4]})
        poids = {graine.oeuvre_id: graine.poids for graine in graines}
        assert poids == {
            1: POIDS_STATUT["aime"],
            2: POIDS_STATUT["aime"],
            3: POIDS_STATUT["a_voir"],
        }
        assert 4 not in poids
        # Les plus fortes d'abord : c'est ce qui survit au plafond.
        assert graines[0].poids >= graines[-1].poids

    def test_a_voir_seul_suffit_a_semer(self) -> None:
        """Une liste d'envies dit déjà quelque chose : elle ne doit pas
        laisser l'onglet muet (elle était ignorée avant ce lot)."""
        moteur = Moteur(None, None, None)  # type: ignore[arg-type]
        assert len(moteur.graines({"aime": [], "a_voir": [7]})) == 1


# ---------------------------------------------------------------------------
# Les sources simulées
# ---------------------------------------------------------------------------


class FauxGraphe:
    """Rend des lignes préparées selon la requête reçue : le voisinage, les
    citations des voisins, ou les proches vectoriels."""

    def __init__(
        self,
        voisins: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
        proches: list[dict[str, Any]] | None = None,
    ) -> None:
        self._voisins = voisins or []
        self._citations = citations or []
        self._proches = proches or []
        self.vues: list[dict[str, Any]] = []

    async def executer(self, cypher: str, **parametres: Any) -> list[dict[str, Any]]:
        self.vues.append({"cypher": cypher, **parametres})
        if "queryNodes" in cypher:
            return self._proches
        if "count(DISTINCT s)" in cypher:
            return self._voisins
        return self._citations


class FauxRecherche:
    """Un Elasticsearch simulé. `None` simule une panne ou un index absent."""

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
            {"quoi": "affinites", "genres": genres, "personnes": personnes, "exclus": exclus}
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
    """La traduction pivot → clé de vignette, telle que `Cles` la lit."""

    def cursor(self) -> Any:
        return self

    async def __aenter__(self) -> FauxConn:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, requete: str, parametres: Any = None) -> None:
        self._pivots = list(parametres["pivots"]) if parametres else []

    async def fetchall(self) -> list[tuple[int, int]]:
        return [(pivot, pivot - 1000) for pivot in self._pivots]


def proche(oeuvre_id: int, distance: float, graine: int = 1001) -> dict[str, Any]:
    return {
        "graine": graine,
        "oeuvreId": oeuvre_id,
        "idTmdb": oeuvre_id - 1000,
        "titre": f"Œuvre {oeuvre_id}",
        "annee": 2020,
        "affiche": None,
        "univers": "series",
        "score": score_de_distance(distance),
    }


def citation(oeuvre_id: int, voisins: int, force: float = 4.0) -> dict[str, Any]:
    return {
        "oeuvreId": oeuvre_id,
        "idTmdb": oeuvre_id - 1000,
        "titre": f"Œuvre {oeuvre_id}",
        "annee": 2019,
        "affiche": None,
        "univers": "series",
        "voisins": voisins,
        "force": force,
    }


async def lancer(
    graphe: FauxGraphe | None,
    recherche: FauxRecherche | None = None,
    cartes: FauxCartes | None = None,
    statuts: dict[str, list[int]] | None = None,
) -> tuple[list[Suggestion], str | None]:
    moteur = Moteur(
        recherche or FauxRecherche(),  # type: ignore[arg-type]
        cartes or FauxCartes(),  # type: ignore[arg-type]
        graphe,  # type: ignore[arg-type]
    )
    return await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        pivots_par_statut=statuts or {"aime": [1001], "aime_pas": [], "a_voir": []},
    )


# ---------------------------------------------------------------------------
# La fusion
# ---------------------------------------------------------------------------


async def test_empreinte_ponderee_par_la_graine() -> None:
    """À distance égale, être proche d'une œuvre vue et aimée vaut plus que
    d'être proche d'une œuvre qu'on veut seulement voir."""
    graphe = FauxGraphe(proches=[proche(2001, 0.5, graine=1001), proche(2002, 0.5, graine=1002)])
    retenues, _ = await lancer(graphe, statuts={"aime": [1001], "a_voir": [1002]})
    par_id = {s.oeuvre_id: s.score for s in retenues}
    assert par_id[2001] > par_id[2002]
    # Et l'apport suit la formule : (1 − d/DISTANCE_MAX) × poids × apport.
    attendu = APPORT_EMPREINTE * (1 - 0.5 / DISTANCE_MAX) * POIDS_STATUT["aime"]
    assert par_id[2001] == pytest.approx(round(attendu, 3), abs=0.01)


async def test_le_plafond_de_distance_ecarte() -> None:
    graphe = FauxGraphe(
        proches=[proche(2001, DISTANCE_MAX - 0.1), proche(2002, DISTANCE_MAX + 0.1)]
    )
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [2001]


async def test_la_communaute_ne_plafonne_plus_les_autres() -> None:
    """LE défaut corrigé : la cascade laissait les tops des voisins — arrêtés
    en 2019 — occuper toutes les places. Ici les deux familles coexistent, et
    une œuvre très proche par l'empreinte passe devant une œuvre portée par
    un seul voisin."""
    graphe = FauxGraphe(
        voisins=[{"membreId": 7, "communes": 1}],
        citations=[citation(3001, voisins=1, force=2.0)],
        proches=[proche(2001, 0.1)],
    )
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [2001, 3001]
    assert {s.source for s in retenues} == {"proche", "voisins"}


async def test_la_corroboration_l_emporte() -> None:
    """Une œuvre moyennement proche mais confirmée par la communauté passe
    devant une œuvre très proche que personne ne cite. C'est la demande :
    deux savoirs indépendants valent mieux qu'un seul très confiant."""
    graphe = FauxGraphe(
        voisins=[{"membreId": 7, "communes": 2}],
        citations=[citation(2002, voisins=5, force=5.0)],
        proches=[proche(2001, 0.15), proche(2002, 0.9)],
    )
    retenues, _ = await lancer(graphe)
    assert retenues[0].oeuvre_id == 2002
    assert retenues[0].corrobore is True
    assert retenues[1].corrobore is False


async def test_la_communaute_seule_reste_possible() -> None:
    """Une œuvre que rien ne rapproche du contenu mais que six voisins citent
    doit pouvoir entrer : le savoir communautaire garde sa voix propre."""
    graphe = FauxGraphe(
        voisins=[{"membreId": 7, "communes": 3}],
        citations=[citation(3001, voisins=6, force=5.0)],
    )
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [3001]
    assert retenues[0].voisins == 6
    # L'apport plafonne à APPORT_COMMUNAUTE : le plus cité de la fournée sert
    # d'échelle, jamais un compte brut.
    assert retenues[0].score == pytest.approx(APPORT_COMMUNAUTE, abs=0.01)


async def test_sans_graphe_les_affinites_repondent() -> None:
    """Ni graphe projeté ni œuvre notée : l'onglet répond quand même."""
    recherche = FauxRecherche(documents=[{"genres": ["Drame"], "personnes": []}], affinites=[7])
    retenues, raison = await lancer(None, recherche, FauxCartes({7: ["Drame", "Comédie"]}))
    assert raison is None
    assert [s.source for s in retenues] == ["affinite"]
    assert retenues[0].oeuvre_id == 1007
    assert retenues[0].cle_vignette == 7
    # Seuls les genres réellement partagés sont nommés.
    assert retenues[0].communs == ["Drame"]


async def test_les_exclusions_couvrent_tous_les_statuts() -> None:
    """Le connu n'est pas une suggestion, l'écarté ne se repropose pas, et
    l'envie est une suggestion déjà acceptée."""
    graphe = FauxGraphe(proches=[proche(2001, 0.2)])
    await lancer(graphe, statuts={"aime": [1001], "aime_pas": [1002], "a_voir": [1003]})
    envoyees = [vue for vue in graphe.vues if "queryNodes" in vue["cypher"]][0]
    assert envoyees["exclues"] == [1001, 1002, 1003]


async def test_les_raisons_du_vide() -> None:
    """Deux vides, deux raisons — et jamais « panne »."""
    _, sans_graine = await lancer(None, statuts={"aime": [], "aime_pas": [9], "a_voir": []})
    assert sans_graine == "aucun_aime"
    _, sans_resultat = await lancer(FauxGraphe())
    assert sans_resultat == "aucun_resultat"


async def test_departage_stable() -> None:
    """À score égal, l'ordre ne doit pas changer d'un appel à l'autre."""
    graphe = FauxGraphe(proches=[proche(2002, 0.3), proche(2001, 0.3)])
    premier, _ = await lancer(graphe)
    second, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in premier] == [s.oeuvre_id for s in second] == [2001, 2002]
