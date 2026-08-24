"""Le moteur de suggestions : les voisins d'abord, la distance pour compléter.

La règle est celle demandée au cahier des charges du composant, et elle a deux
étages parce que le graphe a deux savoirs :

1. **Les voisins, par ordre de priorité.** Un voisin est un membre qui a cité
   les mêmes œuvres que celles que le visiteur a aimées — le savoir
   communautaire, hérité des 66 878 positions de tops de la V1. Ce que ces
   voisins citent et que le visiteur n'a pas classé, c'est la suggestion au
   sens propre. Le classement dit pourquoi une œuvre est là : d'abord le
   nombre de voisins qui la citent, puis leur rang moyen — une œuvre mise en
   première place pèse plus que la même en cinquième (même formule que le
   graphe d'admin, `routes/membres.py`).

2. **La distance de note, petite, pour compléter.** Quand la communauté ne
   suffit pas à remplir la liste, on interroge l'index vectoriel euclidien
   `fivEmpreinteVoisins` : les œuvres dont l'empreinte (les six axes de goût)
   est la plus proche de celles qui ont été aimées. La distance euclidienne
   s'y lit en points de note — la même unité que le MAE de 0,84 du système —
   et elle est PLAFONNÉE : au-delà de `DISTANCE_MAX`, une œuvre n'est plus
   « ce que vous cherchez », c'est du remplissage, et on préfère une liste
   courte à une liste qui ment.

Tout ce qui a déjà été classé est exclu, quel que soit le statut : ce qui est
aimé est connu, ce qui est rejeté a été écarté, ce qui est à voir est une
suggestion déjà acceptée.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from fiv_webapp.graphe import Graphe

# Les voisins retenus. Un voisin à une œuvre commune, il y en a des milliers
# et ils ne disent rien ; on garde ceux qui partagent le plus, et ce plafond
# borne aussi la traversée — une œuvre populaire est citée par 13 817 membres.
VOISINS_MAX = 50

# La liste rendue au composant : une page de cartes, pas un catalogue.
SUGGESTIONS_MAX = 24

# Le nombre de candidats demandés à l'index vectoriel PAR œuvre aimée, avant
# filtrage (univers, exclusions) et plafond de distance.
CANDIDATS_VECTEUR = 50

# Au-delà, deux empreintes ne se ressemblent plus assez pour être proposées :
# ~2,4 fois le MAE du système (0,84) — la limite entre « proche » et
# « vaguement dans le même quadrant ». La liste préfère rester courte.
DISTANCE_MAX = 2.0

# Le voisinage : qui partage le plus d'œuvres aimées avec le visiteur. La
# première étape est bornée par $voisinsMax, et c'est elle qui protège des
# supernœuds — la suite ne traverse plus que 50 membres.
_CY_VOISINS = """
MATCH (s:FivOeuvre) WHERE s.oeuvreId IN $aimes
MATCH (s)<-[:FIV_CITE]-(v:FivMembre)
WITH v, count(DISTINCT s) AS communes
ORDER BY communes DESC, v.membreId
LIMIT $voisinsMax
RETURN v.membreId AS membreId, communes
"""

# Ce que ces voisins citent et que le visiteur n'a pas classé — restreint à
# l'univers demandé : l'onglet « Mes suggestions » se regarde univers par
# univers, comme le reste du site.
_CY_CITATIONS_VOISINS = """
MATCH (v:FivMembre)-[c:FIV_CITE]->(reco:FivOeuvre)
WHERE v.membreId IN $voisins
  AND reco.univers = $univers
  AND NOT reco.oeuvreId IN $exclues
WITH reco, count(DISTINCT v) AS voisins, avg(6 - coalesce(c.rang, 5)) AS force
RETURN reco.oeuvreId AS oeuvreId, reco.idTmdb AS idTmdb, reco.titre AS titre,
       reco.annee AS annee, reco.affiche AS affiche, reco.univers AS univers,
       voisins, force
ORDER BY voisins DESC, force DESC, reco.oeuvreId
LIMIT $limite
"""

# Le complément par l'empreinte : les plus proches voisins vectoriels de
# chaque œuvre aimée. Le score de Neo4j vaut 1/(1+d²) — la distance en points
# de note se retrouve par sqrt(1/score − 1), et c'est SUR ELLE qu'on filtre et
# qu'on classe : un score sans unité ne dirait rien à personne.
#
# `max(score)` par œuvre : être proche d'UNE œuvre aimée suffit — prendre la
# moyenne noierait une correspondance parfaite sous les autres graines.
_CY_PROCHES = """
UNWIND $aimes AS graine
MATCH (s:FivOeuvre {oeuvreId: graine})
WHERE s.empreinte IS NOT NULL
CALL db.index.vector.queryNodes('fivEmpreinteVoisins', $candidats, s.empreinte)
YIELD node, score
WHERE node.univers = $univers
  AND NOT node.oeuvreId IN $exclues
  AND node.oeuvreId <> s.oeuvreId
WITH node, max(score) AS score
RETURN node.oeuvreId AS oeuvreId, node.idTmdb AS idTmdb, node.titre AS titre,
       node.annee AS annee, node.affiche AS affiche, node.univers AS univers, score
ORDER BY score DESC, node.oeuvreId
LIMIT $limite
"""


def distance_depuis_score(score: float) -> float:
    """Le score euclidien de Neo4j (1/(1+d²)) rendu en distance, en points de
    note — l'unité dans laquelle `DISTANCE_MAX` a un sens."""
    if score <= 0.0:
        return math.inf
    return math.sqrt(max(0.0, 1.0 / score - 1.0))


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Une œuvre proposée, avec la raison de sa présence — le composant
    l'affiche : une suggestion inexpliquée ressemble à de la publicité."""

    oeuvre_id: int
    titre: str | None
    annee: int | None
    affiche: str | None
    univers_interne: str
    # `voisins` quand la communauté la porte, `proche` quand c'est l'empreinte.
    source: str
    # L'identifiant TMDB, porté par le nœud — nul pour un livre, qui n'en a
    # pas. C'est lui qui donne la clé de vignette (voir `cle_vignette`), celle
    # que la fiche détaillée attend.
    id_tmdb: int | None = None
    voisins: int | None = None
    force: float | None = None
    distance: float | None = None

    @property
    def cle_vignette(self) -> int:
        """La clé que la carte et la fiche manipulent : l'identifiant TMDB
        quand il existe, le pivot sinon — exactement la règle de
        `univers.pivot_card`."""
        return self.id_tmdb if self.id_tmdb is not None else self.oeuvre_id

    def publique(self, slug: str) -> dict[str, Any]:
        return {
            # `id` est nommé comme sur une carte de recherche, et pour la même
            # raison : c'est la clé qui ouvre la fiche.
            "id": self.cle_vignette,
            "oeuvreId": self.oeuvre_id,
            "titre": self.titre,
            "annee": self.annee,
            "affiche": self.affiche,
            "univers": slug,
            "source": self.source,
            "voisins": self.voisins,
            "force": self.force,
            "distance": self.distance,
        }


class Suggestions:
    """Le moteur : deux lectures du graphe, une liste ordonnée.

    L'ordre de la liste EST la promesse de l'onglet : d'abord ce que les
    voisins portent (par nombre de voisins puis force), ensuite ce qui
    ressemble (par distance croissante) — jamais l'inverse, et jamais mélangé.
    """

    def __init__(self, graphe: Graphe) -> None:
        self._graphe = graphe

    async def pour(
        self,
        *,
        aimes: list[int],
        exclues: list[int],
        univers_interne: str,
        limite: int = SUGGESTIONS_MAX,
    ) -> list[Suggestion]:
        """Les suggestions d'une session : `aimes` est la graine, `exclues`
        tout ce qui a déjà été classé (les aimées comprises)."""
        if not aimes:
            return []

        retenues: list[Suggestion] = []
        vues: set[int] = set(exclues)

        for suggestion in await self._par_voisins(aimes, exclues, univers_interne, limite):
            if suggestion.oeuvre_id not in vues:
                vues.add(suggestion.oeuvre_id)
                retenues.append(suggestion)

        # Le complément vectoriel ne travaille que s'il reste de la place —
        # c'est un complément, pas un concurrent.
        if len(retenues) < limite:
            manque = limite - len(retenues)
            for suggestion in await self._par_distance(aimes, list(vues), univers_interne, manque):
                if suggestion.oeuvre_id not in vues:
                    vues.add(suggestion.oeuvre_id)
                    retenues.append(suggestion)

        return retenues[:limite]

    async def _par_voisins(
        self, aimes: list[int], exclues: list[int], univers_interne: str, limite: int
    ) -> list[Suggestion]:
        voisins = await self._graphe.executer(_CY_VOISINS, aimes=aimes, voisinsMax=VOISINS_MAX)
        if not voisins:
            return []
        lignes = await self._graphe.executer(
            _CY_CITATIONS_VOISINS,
            voisins=[v["membreId"] for v in voisins],
            univers=univers_interne,
            exclues=exclues,
            limite=limite,
        )
        return [
            Suggestion(
                oeuvre_id=ligne["oeuvreId"],
                id_tmdb=ligne.get("idTmdb"),
                titre=ligne["titre"],
                annee=ligne["annee"],
                affiche=ligne["affiche"],
                univers_interne=ligne["univers"],
                source="voisins",
                voisins=int(ligne["voisins"]),
                force=round(float(ligne["force"]), 2) if ligne["force"] is not None else None,
            )
            for ligne in lignes
        ]

    async def _par_distance(
        self, aimes: list[int], exclues: list[int], univers_interne: str, limite: int
    ) -> list[Suggestion]:
        lignes = await self._graphe.executer(
            _CY_PROCHES,
            aimes=aimes,
            candidats=CANDIDATS_VECTEUR,
            univers=univers_interne,
            exclues=exclues,
            limite=limite,
        )
        retenues: list[Suggestion] = []
        for ligne in lignes:
            distance = distance_depuis_score(float(ligne["score"]))
            # Le plafond s'applique ici et pas dans le Cypher : la conversion
            # score → distance est à nous, et un filtre exprimé dans l'unité
            # qu'on affiche est un filtre qu'on peut relire.
            if distance > DISTANCE_MAX:
                continue
            retenues.append(
                Suggestion(
                    oeuvre_id=ligne["oeuvreId"],
                    id_tmdb=ligne.get("idTmdb"),
                    titre=ligne["titre"],
                    annee=ligne["annee"],
                    affiche=ligne["affiche"],
                    univers_interne=ligne["univers"],
                    source="proche",
                    distance=round(distance, 2),
                )
            )
        return retenues
