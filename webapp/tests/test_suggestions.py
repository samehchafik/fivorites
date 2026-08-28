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

import datetime
import math
from typing import Any

import pytest

from fiv_webapp.cartes import Carte
from fiv_webapp.suggestions import (
    APPORT_COMMUNAUTE,
    APPORT_EMPREINTE,
    BONUS_CONVERGENCE,
    DISTANCE_MAX,
    FRAICHEUR_PLANCHER,
    GRAINES_ENVIES_MIN,
    GRAINES_MAX,
    MULTIPLICATEUR_CORROBORATION,
    POIDS_REJET,
    POIDS_STATUT,
    Candidat,
    Moteur,
    Suggestion,
    distance_depuis_score,
    facteur_fraicheur,
    profil_depuis,
    replier_enseignes,
)
from fiv_webapp.univers import UNIVERS

ANNEE_COURANTE = datetime.date.today().year


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


def test_facteur_fraicheur() -> None:
    """Du plus récent au plus vieux : 1,0 cette année, décroissant, jamais
    sous le plancher — l'ancienneté module, elle n'élimine pas."""
    assert facteur_fraicheur(ANNEE_COURANTE) == pytest.approx(1.0)
    assert facteur_fraicheur(ANNEE_COURANTE - 12) < facteur_fraicheur(ANNEE_COURANTE - 4)
    assert facteur_fraicheur(1950) > FRAICHEUR_PLANCHER
    assert facteur_fraicheur(1950) == pytest.approx(FRAICHEUR_PLANCHER, abs=0.01)
    # Sans année : ni punie au plancher, ni prise pour une nouveauté.
    assert FRAICHEUR_PLANCHER < facteur_fraicheur(None) < 1.0


def test_le_score_prefere_le_recent() -> None:
    """À apport égal, l'œuvre récente passe devant : c'est la parade au
    moteur qui se figeait dans les années de la base communautaire."""
    recente = Candidat(oeuvre_id=1, annee=ANNEE_COURANTE - 1)
    ancienne = Candidat(oeuvre_id=2, annee=2005)
    for candidat in (recente, ancienne):
        candidat.verser("proche", 0.8)
    assert recente.score > ancienne.score


class TestCandidat:
    def test_le_plus_fort_apport_gagne(self) -> None:
        """Une source qui parle deux fois de la même œuvre ne cumule pas :
        deux graines vaguement proches ne doivent pas battre une graine très
        proche, sinon un profil large écrase un profil précis."""
        candidat = Candidat(oeuvre_id=1, annee=ANNEE_COURANTE)
        candidat.verser("proche", 0.3)
        candidat.verser("proche", 0.9)
        candidat.verser("proche", 0.5)
        assert candidat.apports["proche"] == 0.9
        # Datée de cette année, la fraîcheur vaut 1,0 : le score EST l'apport.
        assert candidat.score == pytest.approx(0.9)

    def test_corroboration_multiplie(self) -> None:
        """Le geste demandé : contenu ET communauté d'accord → total multiplié."""
        seul = Candidat(oeuvre_id=1)
        seul.verser("proche", 0.5)
        assert not seul.corrobore

        accord = Candidat(oeuvre_id=2, annee=ANNEE_COURANTE)
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
        citations: list[dict[str, Any]] | None = None,
        proches: list[dict[str, Any]] | None = None,
        empreintes: dict[int, list[float]] | None = None,
        profil_proches: list[dict[str, Any]] | None = None,
        gens: list[dict[str, Any]] | None = None,
        genres: list[dict[str, Any]] | None = None,
        membres: int = 1000,
    ) -> None:
        self._citations = citations or []
        self._proches = proches or []
        self._gens = gens or []
        self._genres = genres or []
        self._empreintes = empreintes or {}
        self._profil_proches = profil_proches or []
        self.membres = membres
        self.vues: list[dict[str, Any]] = []
        # Le dernier vecteur de profil interrogé — de quoi vérifier ce que le
        # moteur a réellement demandé à l'index.
        self.profil_demande: list[float] | None = None

    async def executer(self, cypher: str, **parametres: Any) -> list[dict[str, Any]]:
        self.vues.append({"cypher": cypher, **parametres})
        if "empreinte AS empreinte" in cypher:
            return [
                {"oeuvreId": pivot, "empreinte": empreinte}
                for pivot, empreinte in self._empreintes.items()
                if pivot in parametres["pivots"]
            ]
        if "$profil" in cypher:
            self.profil_demande = parametres["profil"]
            return self._profil_proches
        if "FivGenre" in cypher:
            return self._genres
        if "FivPersonne" in cypher:
            return self._gens
        if "UNWIND $graines" in cypher:
            return self._proches
        if "count(m)" in cypher:
            # Le total des membres, dénominateur du taux général.
            return [{"total": self.membres}]
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
    """Les deux lectures SQL du moteur : la traduction pivot → clé de
    vignette (`Cles`), et les plateformes des candidats de tête."""

    def __init__(self, plateformes: dict[str, dict[str, Any]] | None = None) -> None:
        # `plateformes` : source_id → l'objet pays TMDB (`{"flatrate": [...]}`).
        self._plateformes = plateformes or {}
        self._requete = ""

    def cursor(self) -> Any:
        return self

    async def __aenter__(self) -> FauxConn:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, requete: str, parametres: Any = None) -> None:
        self._requete = requete
        if "watch/providers" in requete:
            self._ids = list(parametres["ids"])
        else:
            self._pivots = list(parametres["pivots"]) if parametres else []

    async def fetchall(self) -> list[tuple[Any, Any]]:
        if "watch/providers" in self._requete:
            return [(source_id, self._plateformes.get(source_id, [])) for source_id in self._ids]
        return [(pivot, pivot - 1000) for pivot in self._pivots]


def proche(
    oeuvre_id: int, distance: float, graine: int = 1001, annee: int | None = None
) -> dict[str, Any]:
    return {
        "graine": graine,
        "oeuvreId": oeuvre_id,
        "idTmdb": oeuvre_id - 1000,
        "titre": f"Œuvre {oeuvre_id}",
        # Datées de cette année par défaut : les tests de POLITIQUE regardent
        # les apports, et une fraîcheur de 1,0 les laisse lire tels quels.
        "annee": annee if annee is not None else ANNEE_COURANTE,
        "affiche": None,
        "univers": "series",
        "score": score_de_distance(distance),
    }


def citation(
    oeuvre_id: int,
    voisins: int,
    force: float = 4.0,
    *,
    taille: int = 100,
    citations: int = 50,
) -> dict[str, Any]:
    """Une ligne de la requête communautaire.

    `taille` est le voisinage, `citations` la popularité globale de l'œuvre :
    c'est leur rapport qui décide, pas le compte brut. Avec les valeurs par
    défaut (100 voisins, 50 citations sur 1 000 membres), une œuvre citée par
    20 voisins est à 20 % chez les voisins contre 5 % partout, soit ×4.
    """
    return {
        "oeuvreId": oeuvre_id,
        "idTmdb": oeuvre_id - 1000,
        "titre": f"Œuvre {oeuvre_id}",
        "annee": 2019,
        "affiche": None,
        "univers": "series",
        "voisins": voisins,
        "force": force,
        "taille": taille,
        "citations": citations,
    }


async def lancer(
    graphe: FauxGraphe | None,
    recherche: FauxRecherche | None = None,
    cartes: FauxCartes | None = None,
    statuts: dict[str, list[int]] | None = None,
    conn: FauxConn | None = None,
    **options: Any,
) -> tuple[list[Suggestion], str | None]:
    moteur = Moteur(
        recherche or FauxRecherche(),  # type: ignore[arg-type]
        cartes or FauxCartes(),  # type: ignore[arg-type]
        graphe,  # type: ignore[arg-type]
    )
    retenues, raison, _total = await moteur.pour(
        conn or FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        pivots_par_statut=statuts or {"aime": [1001], "aime_pas": [], "a_voir": []},
        **options,
    )
    return retenues, raison


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
    # Et l'apport suit la formule : (1 − d/DISTANCE_MAX) × poids × apport —
    # fraîcheur 1,0, les fixtures étant datées de cette année.
    attendu = APPORT_EMPREINTE * (1 - 0.5 / DISTANCE_MAX) * POIDS_STATUT["aime"]
    assert par_id[2001] == pytest.approx(round(attendu, 3), abs=0.01)


async def test_le_plafond_de_distance_ecarte() -> None:
    graphe = FauxGraphe(
        proches=[proche(2001, DISTANCE_MAX - 0.1), proche(2002, DISTANCE_MAX + 0.1)]
    )
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [2001]


async def test_la_communaute_ne_plafonne_plus_les_autres() -> None:
    """DEUX défauts corrigés d'un coup.

    La cascade laissait les tops des voisins — arrêtés en 2019 — occuper
    toutes les places : les familles coexistent désormais. Et une œuvre citée
    chez les voisins au même taux que partout ne dit rien : elle se taît, au
    lieu d'arriver première comme Grey's Anatomy le faisait sur une graine
    « Lucifer » (7,4 % chez les fans, 7,9 % partout — mesuré en production).
    """
    graphe = FauxGraphe(
        # Citée par 4 voisins sur 100 (4 %) contre 50 sur 1 000 partout
        # (5 %) : sous-représentée, donc muette — c'est le défaut corrigé.
        citations=[citation(3001, voisins=4, force=2.0)],
        proches=[proche(2001, 0.1)],
    )
    retenues, _ = await lancer(graphe)
    # Seule l'œuvre proche par l'empreinte reste : la sous-représentée n'a
    # versé aucun apport.
    assert [s.oeuvre_id for s in retenues] == [2001]
    assert retenues[0].source == "proche"


async def test_la_corroboration_l_emporte() -> None:
    """Une œuvre moyennement proche mais confirmée par la communauté passe
    devant une œuvre très proche que personne ne cite. C'est la demande :
    deux savoirs indépendants valent mieux qu'un seul très confiant."""
    graphe = FauxGraphe(
        citations=[citation(2002, voisins=30, force=5.0)],
        proches=[proche(2001, 0.15), proche(2002, 0.9)],
    )
    retenues, _ = await lancer(graphe)
    assert retenues[0].oeuvre_id == 2002
    assert retenues[0].corrobore is True
    assert retenues[1].corrobore is False


async def test_la_communaute_seule_reste_possible() -> None:
    """Une œuvre que rien ne rapproche du contenu mais que six voisins citent
    doit pouvoir entrer : le savoir communautaire garde sa voix propre."""
    graphe = FauxGraphe(citations=[citation(3001, voisins=30, force=5.0)])
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [3001]
    assert retenues[0].voisins == 30
    # 30 voisins sur 100 (30 %) contre 50 citations sur 1 000 membres (5 %) :
    # six fois plus souvent que la moyenne. C'est un signal, et il est nommé.
    assert retenues[0].surrepresentation == pytest.approx(6.0)
    # L'apport sature au repère — et le score porte la fraîcheur d'une œuvre
    # de 2019 : la communauté, figée là, ne peut plus dominer une liste.
    attendu = APPORT_COMMUNAUTE * facteur_fraicheur(2019)
    assert retenues[0].score == pytest.approx(attendu, abs=0.01)


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
    envoyees = [vue for vue in graphe.vues if "UNWIND $graines" in vue["cypher"]][0]
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


# ---------------------------------------------------------------------------
# Le lot « la base est figée » : convergence, envies, fraîcheur, masquage
# ---------------------------------------------------------------------------


async def test_la_convergence_fait_monter() -> None:
    """L'œuvre voisine de DEUX graines passe devant l'œuvre voisine d'une
    seule à distance égale — c'est elle qui a le plus de relations avec ce que
    le visiteur aime."""
    graphe = FauxGraphe(
        proches=[
            proche(2001, 0.5, graine=1001),
            proche(2001, 0.5, graine=1002),
            proche(2002, 0.5, graine=1001),
        ]
    )
    retenues, _ = await lancer(graphe, statuts={"aime": [1001, 1002]})
    assert [s.oeuvre_id for s in retenues] == [2001, 2002]
    assert retenues[0].convergences == 2
    # Le bonus suit la formule : base + fraction de la seconde contribution.
    base = APPORT_EMPREINTE * (1 - 0.5 / DISTANCE_MAX)
    assert retenues[0].score == pytest.approx(base * (1 + BONUS_CONVERGENCE), abs=0.01)


async def test_les_envies_ont_des_places_reservees() -> None:
    """Douze « vu et aimé » ne remplissent plus la table : les envies — la
    seule liste qui parle du goût présent — gardent leurs places."""
    moteur = Moteur(FauxRecherche(), FauxCartes(), None)  # type: ignore[arg-type]
    aimes = list(range(1001, 1021))
    envies = list(range(2001, 2011))
    graines = moteur.graines({"aime": aimes, "a_voir": envies})
    assert len(graines) == GRAINES_MAX
    des_envies = [graine for graine in graines if graine.poids == POIDS_STATUT["a_voir"]]
    assert len(des_envies) == GRAINES_ENVIES_MIN


async def test_le_recent_passe_devant_le_vieux() -> None:
    """À proximité égale, la liste se lit du plus récent au plus vieux — la
    parade demandée au moteur qui se figeait dans les années de la base."""
    graphe = FauxGraphe(
        proches=[
            proche(2001, 0.5, annee=2008),
            proche(2002, 0.5, annee=ANNEE_COURANTE - 1),
            proche(2003, 0.5, annee=2015),
        ]
    )
    retenues, _ = await lancer(graphe)
    assert [s.annee for s in retenues] == [ANNEE_COURANTE - 1, 2015, 2008]


async def test_un_vieux_tres_proche_bat_un_recent_vague() -> None:
    """La fraîcheur module, elle n'élimine pas : un chef-d'œuvre ancien collé
    au profil doit encore battre une nouveauté qui ne lui ressemble guère."""
    graphe = FauxGraphe(
        proches=[
            proche(2001, 0.2, annee=1999),
            proche(2002, 1.6, annee=ANNEE_COURANTE),
        ]
    )
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [2001, 2002]


async def test_sans_genres_ecarte() -> None:
    """« Moins de dessins animés » : le genre masqué sort de la liste, sans
    toucher les scores de ce qui reste."""
    graphe = FauxGraphe(proches=[proche(2001, 0.4), proche(2002, 0.6)])
    cartes = FauxCartes(genres_par_id={1001: ["Animation"], 1002: ["Drame"]})
    retenues, _ = await lancer(graphe, cartes=cartes, sans_genres=["animation"])
    assert [s.oeuvre_id for s in retenues] == [2002]
    assert retenues[0].genres == ["Drame"]


# ---------------------------------------------------------------------------
# Les axes du visiteur
# ---------------------------------------------------------------------------


def test_profil_centre_pondere() -> None:
    """Le profil est le centre pondéré des empreintes aimées : un verdict y
    pèse plus qu'une envie."""
    profil = profil_depuis([([2.0, 0.0], 1.0), ([0.0, 2.0], 1.0)], [])
    assert profil == pytest.approx([1.0, 1.0])
    # Pondéré : l'œuvre au poids double tire le centre vers elle.
    penche = profil_depuis([([2.0, 0.0], 1.0), ([0.0, 2.0], 0.5)], [])
    assert penche[0] > penche[1]


def test_profil_repousse_par_les_rejets() -> None:
    """« J'aime pas » cesse d'être un simple filtre : il déplace le profil à
    l'écart du centre des rejets."""
    sans_rejet = profil_depuis([([1.0, 1.0], 1.0)], [])
    avec_rejet = profil_depuis([([1.0, 1.0], 1.0)], [[3.0, 1.0]])
    assert sans_rejet == pytest.approx([1.0, 1.0])
    # Le rejet est à droite du centre : le profil part à gauche, d'une
    # demi-longueur (POIDS_REJET), et l'axe non concerné ne bouge pas.
    assert avec_rejet == pytest.approx([1.0 - POIDS_REJET * 2.0, 1.0])


def test_profil_sans_matiere_positive() -> None:
    """Des rejets seuls ne pointent nulle part : pas de profil, pas de
    requête vectorielle sur du vide."""
    assert profil_depuis([], [[1.0, 2.0]]) is None


async def test_le_profil_interroge_les_axes_du_visiteur() -> None:
    """La source lit les trois listes : aimés et envies font le centre, les
    rejets le déplacent, et c'est CE vecteur qui part à l'index."""
    graphe = FauxGraphe(
        empreintes={1001: [2.0, 0.0], 1002: [0.0, 2.0], 1003: [4.0, 1.0]},
        profil_proches=[
            {
                "oeuvreId": 2001,
                "idTmdb": 1001,
                "titre": "Œuvre 2001",
                "annee": ANNEE_COURANTE,
                "affiche": None,
                "univers": "series",
                "score": score_de_distance(0.4),
            }
        ],
    )
    retenues, _ = await lancer(graphe, statuts={"aime": [1001, 1002], "aime_pas": [1003]})
    assert [s.oeuvre_id for s in retenues] == [2001]
    assert retenues[0].source == "profil"
    # Centre (1,1), rejet (4,1) : le profil fuit le rejet sur le premier axe.
    assert graphe.profil_demande == pytest.approx([1.0 - POIDS_REJET * 3.0, 1.0])


async def test_le_profil_corrobore_avec_la_communaute() -> None:
    """Le profil est une source de CONTENU : d'accord avec la communauté, il
    déclenche la corroboration comme les voisins d'empreinte."""
    candidat = Candidat(oeuvre_id=1, annee=ANNEE_COURANTE)
    candidat.verser("profil", 0.5)
    candidat.verser("voisins", 0.4)
    assert candidat.corrobore


async def test_sur_plateformes_ne_garde_que_le_regardable() -> None:
    """« Sur Netflix » : seuls les candidats disponibles sur une plateforme
    choisie restent — et chaque suggestion porte ses plateformes, la matière
    des puces du front."""
    graphe = FauxGraphe(proches=[proche(2001, 0.4), proche(2002, 0.6)])
    conn = FauxConn(
        plateformes={
            "1001": {"flatrate": [{"provider_name": "Netflix"}]},
            "1002": {"flatrate": [{"provider_name": "Canal+"}]},
        }
    )
    retenues, _ = await lancer(graphe, conn=conn, sur_plateformes=["netflix"])
    assert [s.oeuvre_id for s in retenues] == [2001]
    assert retenues[0].plateformes == [
        {"nom": "Netflix", "acces": "incluse", "via": None, "location": False}
    ]


async def test_sans_plateforme_choisie_tout_reste_et_tout_est_nomme() -> None:
    """Sans filtre, rien ne sort — mais les plateformes sont attachées quand
    l'univers en porte : le front construit ses puces avec."""
    graphe = FauxGraphe(proches=[proche(2001, 0.4)])
    conn = FauxConn(
        plateformes={
            "1001": {"flatrate": [{"provider_name": "Netflix"}, {"provider_name": "Canal+"}]}
        }
    )
    retenues, _ = await lancer(graphe, conn=conn)
    assert [e["nom"] for e in retenues[0].plateformes] == ["Canal+", "Netflix"]


def test_replier_enseignes() -> None:
    """Les offres commerciales se replient sur leur enseigne : « Netflix
    Standard with Ads » est du Netflix, pas une plateforme de plus."""
    assert replier_enseignes(
        ["Netflix", "Netflix Standard with Ads", "Canal+ Séries", "Canal+", "Molotov TV"]
    ) == ["Canal+", "Molotov TV", "Netflix"]
    # Sans enseigne mère présente, la variante reste telle quelle : on ne
    # devine pas une plateforme qui n'est pas dans la donnée.
    assert replier_enseignes(["Netflix Standard with Ads"]) == ["Netflix Standard with Ads"]


async def test_le_filtre_balaie_tout_le_vivier() -> None:
    """Filtrer ne coupe pas d'abord : « sur Netflix » doit aller chercher les
    candidats au-delà de la tête de liste — c'est ce qui faisait fondre la
    liste filtrée alors que la matière existait plus bas au classement."""
    # Quatre candidats classés par proximité ; seul le DERNIER est sur
    # Netflix, et la limite vaut 1 : une coupe de tête avant filtre (1 × 3)
    # l'aurait perdu.
    graphe = FauxGraphe(
        proches=[proche(2001, 0.2), proche(2002, 0.3), proche(2003, 0.4), proche(2004, 0.5)]
    )
    conn = FauxConn(plateformes={"1004": {"flatrate": [{"provider_name": "Netflix"}]}})
    retenues, _ = await lancer(graphe, conn=conn, sur_plateformes=["Netflix"], limite=1)
    assert [s.oeuvre_id for s in retenues] == [2004]


def test_une_chaine_amazon_compte_pour_prime_video() -> None:
    """« HBO Max Amazon Channel » est l'abonnement HBO Max souscrit DANS
    l'appli Prime Video : l'œuvre se regarde dans les deux. Le cas signalé —
    une série que le filtre Prime Video écartait alors que la fiche la
    montrait disponible via Prime."""
    assert replier_enseignes(["HBO Max", "HBO Max Amazon Channel"]) == [
        "Amazon Prime Video",
        "HBO Max",
    ]
    # Le hub déjà présent ne se dédouble pas.
    assert replier_enseignes(["Amazon Prime Video", "Paramount Plus Amazon Channel"]) == [
        "Amazon Prime Video",
        "Paramount Plus",
    ]


def test_qualifier_offres_le_cas_signale() -> None:
    """« A Knight of the Seven Kingdoms » : regardable via HBO Max (en direct
    ou par la chaîne Amazon), à la location sur la boutique de Prime. La
    qualification doit dire les trois choses."""
    from fiv_webapp.suggestions import qualifier_offres

    entrees = qualifier_offres(
        {
            "flatrate": [
                {"provider_name": "HBO Max"},
                {"provider_name": "HBO Max Amazon Channel"},
            ],
            "buy": [{"provider_name": "Amazon Video"}, {"provider_name": "Apple TV Store"}],
        }
    )
    par_nom = {e["nom"]: e for e in entrees}
    assert par_nom["HBO Max"]["acces"] == "incluse"
    # Prime Video : PAS incluse — accessible par la chaîne HBO Max, et la
    # boutique loue aussi.
    prime = par_nom["Amazon Prime Video"]
    assert prime["acces"] == "chaine" and prime["via"] == "HBO Max"
    assert prime["location"] is True
    # Apple TV : location seulement.
    assert par_nom["Apple TV"]["acces"] == "location"


async def test_la_location_seule_ne_fait_pas_matcher() -> None:
    """Presque tout se loue : une œuvre seulement louable sur Prime ne doit
    pas répondre au filtre « sur Prime » — elle s'indique, sans matcher."""
    graphe = FauxGraphe(proches=[proche(2001, 0.4)])
    conn = FauxConn(plateformes={"1001": {"buy": [{"provider_name": "Amazon Video"}]}})
    retenues, _ = await lancer(graphe, conn=conn, sur_plateformes=["Amazon Prime Video"])
    assert retenues == []


# ---------------------------------------------------------------------------
# Les gens : les acteurs et réalisateurs ouvrent sur le récent
# ---------------------------------------------------------------------------


def par_les_gens(
    oeuvre_id: int, gens: int, noms: list[str], importance: float = 10.0
) -> dict[str, Any]:
    return {
        "oeuvreId": oeuvre_id,
        "idTmdb": oeuvre_id - 1000,
        "titre": f"Œuvre {oeuvre_id}",
        "annee": ANNEE_COURANTE,
        "affiche": None,
        "univers": "series",
        "gens": gens,
        "noms": noms,
        "importance": importance,
    }


async def test_les_gens_ouvrent_sur_le_recent() -> None:
    """Une graine sans empreinte mesurée ni citation reste muette pour trois
    sources — ses ACTEURS, eux, sont dans le graphe dès la collecte : ce
    qu'ils ont fait d'autre entre par cette source, avec leurs noms pour
    l'explication."""
    graphe = FauxGraphe(gens=[par_les_gens(2001, 3, ["Melissa Fumero", "Andy Samberg"])])
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [2001]
    assert retenues[0].source == "gens"
    assert retenues[0].gens == 3
    assert retenues[0].avec == ["Melissa Fumero", "Andy Samberg"]


async def test_les_gens_saturent() -> None:
    """Partager une personne est faible — un second rôle prolifique relie
    tout à tout ; en partager beaucoup sature au lieu d'exploser."""
    graphe = FauxGraphe(
        gens=[par_les_gens(2001, 1, ["A"]), par_les_gens(2002, 7, ["B", "C", "D", "E"])]
    )
    retenues, _ = await lancer(graphe)
    par_id = {s.oeuvre_id: s.score for s in retenues}
    assert par_id[2002] > par_id[2001]
    # 7 personnes dépassent le repère : l'apport est plafonné à APPORT_GENS.
    from fiv_webapp.suggestions import APPORT_GENS

    assert par_id[2002] == pytest.approx(APPORT_GENS, abs=0.01)


async def test_les_gens_corroborent_avec_la_communaute() -> None:
    """Les gens sont une source de CONTENU : d'accord avec la communauté,
    ils déclenchent la corroboration."""
    candidat = Candidat(oeuvre_id=1, annee=ANNEE_COURANTE)
    candidat.verser("gens", 0.5)
    candidat.verser("voisins", 0.4)
    assert candidat.corrobore


async def test_la_pagination_decoupe_le_vivier() -> None:
    """La page 2 continue exactement là où la première s'arrête — pages
    disjointes, total annoncé, et une page au-delà de la fin n'est pas une
    panne."""
    graphe = FauxGraphe(proches=[proche(2000 + i, 0.2 + i * 0.02) for i in range(1, 8)])
    moteur = Moteur(FauxRecherche(), FauxCartes(), graphe)  # type: ignore[arg-type]
    statuts = {"aime": [1001], "aime_pas": [], "a_voir": []}
    page1, raison1, total1 = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        pivots_par_statut=statuts,
        limite=3,
        depuis=0,
    )
    page2, raison2, total2 = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        pivots_par_statut=statuts,
        limite=3,
        depuis=3,
    )
    assert total1 == total2 == 7
    assert [s.oeuvre_id for s in page1] == [2001, 2002, 2003]
    assert [s.oeuvre_id for s in page2] == [2004, 2005, 2006]
    assert raison1 is None and raison2 is None
    # Au-delà de la fin : vide, sans raison d'erreur — la liste est parcourue.
    apres, raison3, _ = await moteur.pour(
        FauxConn(),  # type: ignore[arg-type]
        UNIVERS["series"],
        pivots_par_statut=statuts,
        limite=3,
        depuis=9,
    )
    assert apres == [] and raison3 is None


async def test_les_gens_pesent_par_leur_indice() -> None:
    """Un lien par une tête d'affiche mondiale (indice 10) pèse plus qu'un
    lien par des inconnus (indice 1) — sans que ce dernier tombe à zéro :
    les acteurs d'un cinéma local restent un vrai lien."""
    graphe = FauxGraphe(
        gens=[
            par_les_gens(2001, 2, ["Star"], importance=10.0),
            par_les_gens(2002, 2, ["Inconnu"], importance=1.0),
        ]
    )
    retenues, _ = await lancer(graphe)
    par_id = {s.oeuvre_id: s.score for s in retenues}
    assert par_id[2001] > par_id[2002] > 0
    from fiv_webapp.suggestions import PLANCHER_IMPORTANCE

    # Les proportions suivent la formule : plancher + pente × indice/10.
    attendu = (PLANCHER_IMPORTANCE + (1 - PLANCHER_IMPORTANCE) * 0.1) / 1.0
    assert par_id[2002] / par_id[2001] == pytest.approx(attendu, abs=0.01)


async def test_les_genres_ouvrent_aussi() -> None:
    """La relation genre du graphe entre enfin dans le moteur : une œuvre qui
    partage les genres de plusieurs graines est candidate, expliquée par les
    genres nommés — et sans dépendre d'Elasticsearch."""
    graphe = FauxGraphe(
        genres=[
            {
                "oeuvreId": 2001,
                "idTmdb": 1001,
                "titre": "Œuvre 2001",
                "annee": ANNEE_COURANTE,
                "affiche": None,
                "univers": "series",
                "liens": 8,
                "genres": 3,
                "noms": ["Mystère", "Science-Fiction & Fantastique", "Drame"],
            }
        ]
    )
    retenues, _ = await lancer(graphe)
    assert [s.oeuvre_id for s in retenues] == [2001]
    assert retenues[0].source == "genre"
    assert retenues[0].communs[:2] == ["Mystère", "Science-Fiction & Fantastique"]
    import math

    from fiv_webapp.suggestions import APPORT_GENRE, GENRES_LIENS_REPERE

    # L'apport suit la saturation en log des liens.
    attendu = APPORT_GENRE * min(1.0, math.log(1 + 8) / math.log(1 + GENRES_LIENS_REPERE))
    assert retenues[0].score == pytest.approx(attendu, abs=0.01)


async def test_le_genre_corrobore_avec_la_communaute() -> None:
    candidat = Candidat(oeuvre_id=1, annee=ANNEE_COURANTE)
    candidat.verser("genre", 0.3)
    candidat.verser("voisins", 0.3)
    assert candidat.corrobore
