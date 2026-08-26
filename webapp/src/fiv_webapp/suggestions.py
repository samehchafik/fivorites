"""Le moteur de suggestions : trois étages, du signal le plus fort au plus large.

La règle demandée au cahier des charges — les voisins d'abord, la distance
d'empreinte pour compléter — est celle des deux premiers étages. Le
troisième a été ajouté après coup, et il faut dire pourquoi : **les deux
premiers ne répondaient presque jamais.**

Ce qu'ils exigent, mesuré sur le catalogue : qu'un membre de la V1 ait cité
l'œuvre aimée (66 878 citations pour 228 000 séries — l'immense majorité du
catalogue n'est citée par personne), ou qu'elle porte une empreinte, donc
qu'elle ait été notée (une campagne à la fois, quelques milliers d'œuvres).
Aimer une série ordinaire ne déclenchait donc rien, et l'onglet restait vide
sans qu'on sache si c'était une panne ou un état.

Le troisième étage n'a pas cette faiblesse : **un genre et une distribution,
toute œuvre collectée en a.** Il est servi par l'index Elasticsearch, qui
porte les deux depuis le lot précédent, et il ne demande pas Neo4j — les
suggestions existent donc même sans graphe projeté.

Les trois, dans l'ordre :

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

3. **Les affinités, pour qu'il y ait toujours une réponse.** Les genres et
   les gens des œuvres aimées, cherchés dans l'index : classement par nombre
   de points communs multiplié par la note bayésienne, affiche exigée. C'est
   le plus faible des trois signaux — partager un genre n'est pas partager un
   goût — d'où sa place, en dernier, et l'explication qui l'accompagne à
   l'écran : le visiteur doit pouvoir faire la différence entre « des gens
   comme vous ont aimé » et « ça ressemble ».

Tout ce qui a déjà été classé est exclu, quel que soit le statut : ce qui est
aimé est connu, ce qui est rejeté a été écarté, ce qui est à voir est une
suggestion déjà acceptée.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fiv_webapp.cartes import Cartes
from fiv_webapp.graphe import Graphe
from fiv_webapp.recherche import Recherche
from fiv_webapp.univers import Univers

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

# Les œuvres aimées dont on lit les genres et les gens pour bâtir l'étage des
# affinités. Les plus récemment classées d'abord : un profil se déplace, et
# soixante coups de cœur feraient une requête aussi large que le catalogue.
GRAINES_AFFINITE = 8

# Ce qu'on retient d'une graine. Trois genres, c'est déjà tout ce qu'une fiche
# TMDB porte ; six personnes, c'est la tête d'affiche — au-delà, on relie des
# œuvres par un second rôle, ce qui ne veut rien dire.
GENRES_PAR_GRAINE = 3
PERSONNES_PAR_GRAINE = 6

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
    # D'où elle vient : `voisins` quand la communauté la porte, `proche`
    # quand c'est l'empreinte, `affinite` quand ce sont les genres et les
    # gens. Le front l'affiche — une suggestion inexpliquée ressemble à de la
    # publicité, et les trois n'ont pas la même force.
    source: str
    # L'identifiant TMDB, porté par le nœud — nul pour un livre, qui n'en a
    # pas. C'est lui qui donne la clé de vignette (voir `cle_vignette`), celle
    # que la fiche détaillée attend.
    id_tmdb: int | None = None
    voisins: int | None = None
    force: float | None = None
    distance: float | None = None
    # Ce que l'œuvre partage avec les coups de cœur — les genres communs,
    # nommés. Sert l'explication de l'étage des affinités.
    communs: list[str] = field(default_factory=list)

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
            "communs": self.communs,
        }


class Cles:
    """La correspondance entre les deux identités du système.

    Les signaux stockent le **pivot** (`sourcing.oeuvre.id`), la seule clé
    commune aux trois univers ; l'index et les vignettes travaillent sur la
    **clé de vignette** (l'identifiant TMDB, ou le pivot pour les livres).
    Traduire entre les deux est le genre de détail qu'on écrit une fois, ici,
    plutôt que dans chaque étage.
    """

    async def vignettes(
        self, conn: psycopg.AsyncConnection, univers: Univers, pivots: list[int]
    ) -> dict[int, int]:
        """pivot → clé de vignette, pour les pivots qui existent."""
        if not pivots:
            return {}
        if univers.pivot_card:
            # Un livre EST désigné par son pivot : rien à traduire.
            return {pivot: pivot for pivot in pivots}
        async with conn.cursor() as cur:
            await cur.execute(
                "select id, id_tmdb from oeuvre"
                " where univers = %(univers)s and id = any(%(pivots)s) and id_tmdb is not null",
                {"univers": univers.interne, "pivots": pivots},
            )
            return {pivot: id_tmdb for pivot, id_tmdb in await cur.fetchall()}


class Affinites:
    """Le troisième étage : ce qui partage les genres et les gens des œuvres
    aimées, servi par l'index de recherche.

    Il ne demande ni graphe projeté ni œuvre notée — c'est sa raison d'être :
    tant que les deux étages du dessus restent creux, c'est lui qui fait que
    l'onglet répond quelque chose.
    """

    def __init__(self, recherche: Recherche, cartes: Cartes) -> None:
        self._recherche = recherche
        self._cartes = cartes
        self._cles = Cles()

    async def pour(
        self,
        conn: psycopg.AsyncConnection,
        univers: Univers,
        *,
        aimes: list[int],
        exclues: list[int],
        limite: int,
    ) -> list[Suggestion]:
        cles = await self._cles.vignettes(conn, univers, aimes + exclues)
        graines = [cles[pivot] for pivot in aimes[:GRAINES_AFFINITE] if pivot in cles]
        if not graines:
            return []

        documents = await self._recherche.documents(univers, graines)
        if not documents:
            return []

        genres = self._retenir(documents, "genres", GENRES_PAR_GRAINE)
        personnes = self._retenir(documents, "personnes", PERSONNES_PAR_GRAINE)
        trouvees = await self._recherche.affinites(
            univers,
            genres=genres,
            personnes=personnes,
            exclus=[cles[pivot] for pivot in exclues if pivot in cles],
            taille=limite,
        )
        if not trouvees:
            return []

        # L'hydratation passe par les vignettes, comme la recherche : une
        # seule source de vérité pour ce qui s'affiche.
        cartes = await self._cartes.hydrater(conn, univers, trouvees)
        aimes_genres = set(genres)
        return [
            Suggestion(
                oeuvre_id=carte.oeuvre_id,
                id_tmdb=None if univers.pivot_card else carte.id,
                titre=carte.titre or carte.titre_original,
                annee=carte.annee,
                affiche=carte.affiche,
                univers_interne=univers.interne,
                source="affinite",
                # Les genres partagés, nommés : c'est ce qui rend la
                # suggestion explicable. Vide quand la correspondance s'est
                # faite sur un nom — on ne l'affirme pas faute de le savoir.
                communs=[genre for genre in carte.genres if genre in aimes_genres],
            )
            for carte in cartes
            if carte.oeuvre_id is not None
        ]

    def _retenir(self, documents: list[dict[str, Any]], champ: str, par_document: int) -> list[str]:
        """Les valeurs les plus fréquentes du champ, dédupliquées.

        Fréquentes d'abord : un genre que trois coups de cœur partagent dit
        mieux le goût qu'un genre vu une fois, et c'est lui qu'on veut au
        cœur de la requête.
        """
        comptes: dict[str, int] = {}
        for document in documents:
            valeurs = document.get(champ) or []
            if isinstance(valeurs, str):
                valeurs = [valeurs]
            for valeur in valeurs[:par_document]:
                nettoyee = (valeur or "").strip()
                if nettoyee:
                    comptes[nettoyee] = comptes.get(nettoyee, 0) + 1
        return sorted(comptes, key=lambda valeur: (-comptes[valeur], valeur))


class Suggestions:
    """Les deux étages du graphe : la communauté, puis l'empreinte.

    L'ordre EST la promesse de l'onglet : d'abord ce que les voisins portent
    (par nombre de voisins puis force), ensuite ce qui ressemble (par distance
    croissante) — jamais l'inverse, et jamais mélangé.
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


class Moteur:
    """Les trois étages, dans l'ordre, et l'arrêt dès que la liste est pleine.

    C'est le seul objet que la route connaît. Il tient deux promesses :

    * **l'ordre** — la communauté, puis l'empreinte, puis les affinités ; un
      signal faible ne passe jamais devant un signal fort ;
    * **une réponse** — le dernier étage ne demande ni graphe ni notation, si
      bien qu'un visiteur qui a aimé une œuvre collectée obtient toujours
      quelque chose. Quand il n'obtient rien, `raison` dit laquelle des
      conditions manque, et le front l'affiche : une liste vide sans
      explication se confond avec une panne.
    """

    def __init__(self, recherche: Recherche, cartes: Cartes, graphe: Graphe | None = None) -> None:
        self._graphe = graphe
        self._affinites = Affinites(recherche, cartes)

    async def pour(
        self,
        conn: psycopg.AsyncConnection,
        univers: Univers,
        *,
        aimes: list[int],
        exclues: list[int],
        limite: int = SUGGESTIONS_MAX,
    ) -> tuple[list[Suggestion], str | None]:
        """La liste et, si elle est vide, la raison de l'être."""
        if not aimes:
            return [], "aucun_aime"

        retenues: list[Suggestion] = []
        vues: set[int] = set(exclues)

        if self._graphe is not None:
            graphe = Suggestions(self._graphe)
            for suggestion in await graphe.pour(
                aimes=aimes,
                exclues=exclues,
                univers_interne=univers.interne,
                limite=limite,
            ):
                if suggestion.oeuvre_id not in vues:
                    vues.add(suggestion.oeuvre_id)
                    retenues.append(suggestion)

        # Les affinités ne travaillent que s'il reste de la place : elles
        # complètent la communauté et l'empreinte, elles ne les remplacent pas.
        if len(retenues) < limite:
            for suggestion in await self._affinites.pour(
                conn,
                univers,
                aimes=aimes,
                exclues=sorted(vues),
                limite=limite - len(retenues),
            ):
                if suggestion.oeuvre_id not in vues:
                    vues.add(suggestion.oeuvre_id)
                    retenues.append(suggestion)

        if retenues:
            return retenues[:limite], None
        # Rien du tout : la cause est presque toujours la même — l'œuvre
        # aimée n'est pas dans l'index de cet univers (jamais collectée, ou
        # `search reindex` pas encore passé). Le dire vaut mieux que laisser
        # croire à une panne.
        return [], "aucun_resultat"
