"""La filmographie d'une personne — ce qui s'ouvre au clic sur un visage.

Deux chemins, et le second existe parce que le premier est facultatif :

* **le graphe** (Neo4j) est la source juste. Une personne y est un nœud
  identifié par sa clé — `tmdb:1234`, `wd:Q535` — et ses œuvres sont ses
  relations : `FIV_JOUE_DANS`, `FIV_A_REALISE`, `FIV_A_CREE`. On obtient donc
  sa filmographie **exacte et tous univers confondus**, sans risque
  d'homonyme : deux « John Ford » sont deux nœuds ;
* **l'index** (Elasticsearch) en repli, par le NOM. Moins juste — deux
  homonymes se confondent, et la recherche se limite à un univers, celui de
  l'alias interrogé — mais disponible quand le graphe ne l'est pas, et un
  visiteur qui clique sur un acteur préfère une liste imparfaite à un panneau
  vide. La réponse dit lequel des deux chemins a servi.

La pagination est de dix œuvres, comme demandé : une page se lit d'un coup
d'œil, et une filmographie de Samuel L. Jackson en compte deux cents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fiv_webapp.cartes import Cartes
from fiv_webapp.graphe import Graphe
from fiv_webapp.recherche import Recherche
from fiv_webapp.univers import UNIVERS, Univers

# La forme d'une clé de personne. Vérifiée avant d'entrer dans une requête :
# c'est un paramètre lié, donc jamais interpolé, mais un identifiant qui ne
# ressemble à rien mérite un 400 plutôt qu'une liste vide inexplicable.
CLE_VALIDE = re.compile(r"^(tmdb|wd):[A-Za-z0-9]+$")

# La page, comme demandé.
PAR_PAGE = 10

# Le plafond de pagination. Au-delà, personne ne déroule : les filmographies
# les plus longues du catalogue tiennent largement dessous.
PAGE_MAX = 30

# Les métiers qu'on montre, et leur libellé. Ce sont les trois relations que
# la projection du graphe pose (`fiv_admin.graphe.LABEL_DU_ROLE`).
# Le rôle sort en CODE, pas en français : la même filmographie se lit en
# quatre langues, et « Interprétation » dans une page arabe serait une faute
# de plus qu'un manque. Le front les traduit (`src/i18n/textes`, clés
# `role.*`).
ROLES = {
    "FIV_JOUE_DANS": "interpretation",
    "FIV_A_REALISE": "realisation",
    "FIV_A_CREE": "creation",
}


@dataclass(frozen=True, slots=True)
class OeuvreDePersonne:
    """Une œuvre de la filmographie, sous la forme d'une carte."""

    # La clé de vignette : c'est elle qui ouvre la fiche.
    id: int
    oeuvre_id: int
    univers: str
    titre: str | None
    annee: int | None
    affiche: str | None
    role: str | None

    def publique(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "oeuvreId": self.oeuvre_id,
            "univers": self.univers,
            "titre": self.titre,
            "annee": self.annee,
            "affiche": self.affiche,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class FichePersonne:
    """Quelqu'un, sa photo, et une page de ses œuvres."""

    cle: str
    nom: str | None
    photo: str | None
    oeuvres: list[OeuvreDePersonne] = field(default_factory=list)
    total: int = 0
    page: int = 1
    # `graphe` ou `index` : le front le dit, parce qu'une filmographie tirée
    # du nom peut mélanger deux homonymes et que le visiteur a le droit de le
    # savoir.
    source: str = "graphe"

    def publique(self) -> dict[str, Any]:
        return {
            "cle": self.cle,
            "nom": self.nom,
            "photo": self.photo,
            "oeuvres": [oeuvre.publique() for oeuvre in self.oeuvres],
            "total": self.total,
            "page": self.page,
            "parPage": PAR_PAGE,
            "source": self.source,
        }


# La personne et son compte d'œuvres. Deux requêtes plutôt qu'une : le total
# sert la pagination et se compte par degré, sans traverser.
_CY_PERSONNE = """
MATCH (p:FivPersonne {cle: $cle})
RETURN p.nom AS nom, p.photo AS photo,
       count { (p)-[r]->(:FivOeuvre) WHERE type(r) IN $roles } AS total
"""

# Une page de sa filmographie, la plus récente d'abord — c'est l'ordre qu'on
# attend d'une filmographie, et il départage sur le pivot pour qu'une même
# année ne change pas d'ordre d'une page à l'autre.
#
# `o.annee IS NULL` en tête du tri, et ce n'est pas un détail : un tri
# décroissant met les valeurs nulles EN PREMIER dans Neo4j, si bien que la
# filmographie d'Henry Cavill s'ouvrait sur « Untitled McG Film », « Voltron »
# et « Broadsword » — des projets annoncés sans date — avant ses films sortis.
# Vérifié sur la production.
_CY_OEUVRES = """
MATCH (p:FivPersonne {cle: $cle})-[r]->(o:FivOeuvre)
WHERE type(r) IN $roles
RETURN o.oeuvreId AS oeuvreId, o.idTmdb AS idTmdb, o.titre AS titre,
       o.annee AS annee, o.affiche AS affiche, o.univers AS univers,
       type(r) AS role
ORDER BY o.annee IS NULL, o.annee DESC, o.oeuvreId
SKIP $depuis LIMIT $taille
"""


class Personnes:
    """La lecture d'une filmographie, par le graphe ou par l'index."""

    def __init__(self, recherche: Recherche, cartes: Cartes, graphe: Graphe | None = None) -> None:
        self._recherche = recherche
        self._cartes = cartes
        self._graphe = graphe

    async def pour(
        self,
        conn: psycopg.AsyncConnection,
        cle: str,
        *,
        page: int = 1,
        univers: Univers | None = None,
        nom: str | None = None,
    ) -> FichePersonne | None:
        """La personne et une page de ses œuvres, ou `None` si on ne sait rien
        d'elle.

        `univers` et `nom` ne servent qu'au repli par l'index : sans graphe, on
        ne peut chercher que par le nom, et dans un univers à la fois.
        """
        if self._graphe is not None:
            trouvee = await self._par_graphe(cle, page)
            if trouvee is not None:
                return trouvee
        if univers is not None and nom:
            return await self._par_index(conn, cle, nom, univers, page)
        return None

    async def _par_graphe(self, cle: str, page: int) -> FichePersonne | None:
        assert self._graphe is not None
        roles = list(ROLES)
        entetes = await self._graphe.executer(_CY_PERSONNE, cle=cle, roles=roles)
        if not entetes:
            return None
        entete = entetes[0]
        lignes = await self._graphe.executer(
            _CY_OEUVRES,
            cle=cle,
            roles=roles,
            depuis=(page - 1) * PAR_PAGE,
            taille=PAR_PAGE,
        )
        slugs = {media.interne: media.slug for media in UNIVERS.values()}
        pivots = {media.interne: media.pivot_card for media in UNIVERS.values()}
        return FichePersonne(
            cle=cle,
            nom=entete.get("nom"),
            photo=entete.get("photo"),
            total=int(entete.get("total") or 0),
            page=page,
            source="graphe",
            oeuvres=[
                OeuvreDePersonne(
                    # La clé de vignette : le pivot pour un livre, l'id TMDB
                    # sinon — la règle de `univers.pivot_card`.
                    id=(
                        ligne["oeuvreId"]
                        if pivots.get(ligne.get("univers"), False)
                        else ligne.get("idTmdb") or ligne["oeuvreId"]
                    ),
                    oeuvre_id=ligne["oeuvreId"],
                    univers=slugs.get(ligne.get("univers"), ligne.get("univers") or ""),
                    titre=ligne.get("titre"),
                    annee=ligne.get("annee"),
                    affiche=ligne.get("affiche"),
                    role=ROLES.get(ligne.get("role") or ""),
                )
                for ligne in lignes
            ],
        )

    async def _par_index(
        self,
        conn: psycopg.AsyncConnection,
        cle: str,
        nom: str,
        univers: Univers,
        page: int,
    ) -> FichePersonne | None:
        """Le repli : les œuvres de l'index dont le champ `personnes` porte ce
        nom. Un seul univers, et les homonymes confondus — la réponse le dit."""
        page_ids = await self._recherche.par_personne(
            univers, nom, depuis=(page - 1) * PAR_PAGE, taille=PAR_PAGE
        )
        if page_ids is None:
            return None
        cartes = await self._cartes.hydrater(conn, univers, page_ids.ids)
        return FichePersonne(
            cle=cle,
            nom=nom,
            # L'index ne porte pas les photos des gens : le front garde celle
            # qu'il affichait déjà, il n'a pas besoin qu'on la lui rende.
            photo=None,
            total=page_ids.total,
            page=page,
            source="index",
            oeuvres=[
                OeuvreDePersonne(
                    id=carte.id,
                    oeuvre_id=carte.oeuvre_id or carte.id,
                    univers=univers.slug,
                    titre=carte.titre or carte.titre_original,
                    annee=carte.annee,
                    affiche=carte.affiche,
                    role=None,
                )
                for carte in cartes
            ],
        )
