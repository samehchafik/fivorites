"""Le moteur de suggestions : une fusion pondérée, pas une cascade.

**Ce qu'il faisait, et pourquoi c'était faux.** Trois étages en cascade — les
tops des voisins, puis la distance d'empreinte, puis les affinités — le
premier remplissant les vingt-quatre places avant que les suivants ne
tournent. Or le savoir communautaire est celui de la V1, **arrêté en 2019** :
qui aime une œuvre récente n'était servi que par des tops qui ne la
connaissent pas, et les étages capables de le servir ne s'exécutaient jamais.
Une cascade fait de son premier étage un plafond.

**Ce qu'il fait maintenant.** Chaque source propose des candidats avec un
apport chiffré, les apports s'additionnent, et le classement se fait sur le
total. Aucune source ne peut donc occuper la liste à elle seule.

Les GRAINES sont les listes du visiteur, pondérées par ce qu'elles disent :

* `aime` — « j'ai vu et aimé » : un verdict. Poids plein.
* `a_voir` — « je veux voir » : une intention, qui dit le goût sans le
  prouver. Poids réduit — et c'est un gain, elles étaient jusqu'ici ignorées
  comme graines.
* `aime_pas` — exclu des graines et des résultats.

Les SOURCES, et ce que chacune sait :

1. **Les voisins d'œuvre par empreinte** (Neo4j, index vectoriel euclidien).
   La distance se lit en points de note — la même unité que le MAE de 0,84 du
   système — et l'apport décroît avec elle jusqu'à s'annuler à
   `DISTANCE_MAX`. Couvre tout ce qui est noté, sans date de péremption.
2. **Les affinités** (Elasticsearch : genres et gens des graines). Le signal
   le plus faible — partager un genre n'est pas partager un goût — mais le
   seul qui ait toujours de la matière, sur tout le catalogue.
3. **La communauté** (Neo4j : les membres qui citent les graines, et ce
   qu'ils citent d'autre). Un apport propre, plus modeste qu'avant.

Et le geste que ce lot ajoute : **la corroboration**. Quand une œuvre est à la
fois proche par le contenu ET portée par la communauté, son total est
multiplié. Deux savoirs indépendants qui désignent la même œuvre valent mieux
que deux fois le même — c'est le cœur de ce qui a été demandé, et c'est aussi
ce qui laisse la communauté peser fort là où elle a raison, sans lui laisser
tenir la liste là où elle est muette.

Tout ce qui a déjà été classé reste exclu, quel que soit le statut.
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

# --- Les poids des graines -------------------------------------------------
#
# « J'ai vu et aimé » est un verdict, « je veux voir » une intention : les
# traiter à égalité ferait dériver le profil vers une liste d'envies, dont
# rien ne dit encore qu'elles ont plu.
POIDS_STATUT = {"aime": 1.0, "a_voir": 0.4}

# Les graines retenues, les plus récemment classées d'abord : un profil se
# déplace, et soixante coups de cœur feraient une requête aussi large que le
# catalogue.
GRAINES_MAX = 12

# --- Les apports des sources ----------------------------------------------
#
# Ils se lisent comme un ordre de confiance : l'empreinte (six axes de goût
# mesurés) au-dessus de la communauté (des gens qui ont aimé les mêmes
# choses), elle-même au-dessus des affinités (un genre, un acteur en commun).
APPORT_EMPREINTE = 1.0
APPORT_COMMUNAUTE = 0.8
APPORT_AFFINITE = 0.55

# La corroboration : le multiplicateur appliqué au total d'une œuvre que DEUX
# familles de sources désignent — le contenu (empreinte ou affinités) et la
# communauté. C'est la demande à l'origine de ce lot, et le chiffre est
# volontairement fort : un accord entre deux savoirs indépendants est ce qu'on
# a de plus proche d'une preuve.
MULTIPLICATEUR_CORROBORATION = 1.8

# --- Les plafonds ----------------------------------------------------------

# Les voisins retenus. Un voisin à une œuvre commune, il y en a des milliers
# et ils ne disent rien ; on garde ceux qui partagent le plus, et ce plafond
# borne aussi la traversée — une œuvre populaire est citée par 13 817 membres.
VOISINS_MAX = 50

# La liste rendue au composant : une page de cartes, pas un catalogue.
SUGGESTIONS_MAX = 24

# Les candidats demandés à chaque source avant fusion. Large : c'est le
# recouvrement entre sources qui fait la corroboration, et un pool étroit le
# rendrait rare par construction.
CANDIDATS_PAR_SOURCE = 60

# Le nombre de voisins vectoriels demandés PAR graine.
CANDIDATS_VECTEUR = 40

# Au-delà, deux empreintes ne se ressemblent plus assez pour être proposées :
# ~2,4 fois le MAE du système (0,84) — la limite entre « proche » et
# « vaguement dans le même quadrant ». L'apport décroît linéairement jusque-là
# puis s'annule.
DISTANCE_MAX = 2.0

# Ce qu'on retient d'une graine pour bâtir la requête d'affinités. Trois
# genres, c'est déjà tout ce qu'une fiche TMDB porte ; six personnes, c'est la
# tête d'affiche — au-delà, on relie des œuvres par un second rôle.
GENRES_PAR_GRAINE = 3
PERSONNES_PAR_GRAINE = 6

# Le voisinage : qui partage le plus de graines avec le visiteur. La première
# étape est bornée par $voisinsMax, et c'est elle qui protège des supernœuds —
# la suite ne traverse plus que cinquante membres.
#
# `graines` porte les pivots ; leur poids reste côté Python, où il se lit.
_CY_VOISINS = """
MATCH (s:FivOeuvre) WHERE s.oeuvreId IN $graines
MATCH (s)<-[:FIV_CITE]-(v:FivMembre)
WITH v, count(DISTINCT s) AS communes
ORDER BY communes DESC, v.membreId
LIMIT $voisinsMax
RETURN v.membreId AS membreId, communes
"""

# Ce que ces voisins citent et que le visiteur n'a pas classé — restreint à
# l'univers demandé : l'onglet se regarde univers par univers.
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

# Les voisins d'ŒUVRE par empreinte : pour chaque graine, ses plus proches
# dans l'espace des six axes. Le score de Neo4j vaut 1/(1+d²) — la distance en
# points de note se retrouve par sqrt(1/score − 1), et c'est sur elle qu'on
# raisonne : un score sans unité ne dirait rien à personne.
#
# La requête rend UNE LIGNE PAR COUPLE (graine, candidat), là où elle prenait
# avant le `max` par candidat. C'est ce qui permet de pondérer par la graine :
# être proche d'une œuvre qu'on a vue et aimée ne vaut pas être proche d'une
# œuvre qu'on veut voir. Le volume reste borné — douze graines par quarante
# candidats.
_CY_PROCHES = """
UNWIND $graines AS graine
MATCH (s:FivOeuvre {oeuvreId: graine})
WHERE s.empreinte IS NOT NULL
CALL db.index.vector.queryNodes('fivEmpreinteVoisins', $candidats, s.empreinte)
YIELD node, score
WHERE node.univers = $univers
  AND NOT node.oeuvreId IN $exclues
  AND node.oeuvreId <> s.oeuvreId
RETURN graine, node.oeuvreId AS oeuvreId, node.idTmdb AS idTmdb, node.titre AS titre,
       node.annee AS annee, node.affiche AS affiche, node.univers AS univers, score
ORDER BY score DESC
LIMIT $limite
"""


def distance_depuis_score(score: float) -> float:
    """Le score euclidien de Neo4j (1/(1+d²)) rendu en distance, en points de
    note — l'unité dans laquelle `DISTANCE_MAX` a un sens."""
    if score <= 0.0:
        return math.inf
    return math.sqrt(max(0.0, 1.0 / score - 1.0))


@dataclass(frozen=True, slots=True)
class Graine:
    """Une œuvre du visiteur et ce qu'elle pèse.

    Le poids vient du statut : un verdict (« vu et aimé ») ne dit pas la même
    chose qu'une intention (« je veux voir »), et le moteur ne doit pas les
    confondre.
    """

    oeuvre_id: int
    poids: float


@dataclass(slots=True)
class Candidat:
    """Une œuvre proposée, en cours de construction.

    Mutable, contrairement au reste du module : c'est un accumulateur, les
    sources y versent leurs apports l'une après l'autre. Il devient une
    `Suggestion` — figée — au moment du classement.
    """

    oeuvre_id: int
    id_tmdb: int | None = None
    titre: str | None = None
    annee: int | None = None
    affiche: str | None = None
    univers_interne: str = ""
    # L'apport de chaque source, nommé. Garder le détail plutôt qu'un total
    # opaque, c'est pouvoir expliquer la suggestion à l'écran et pouvoir
    # régler les poids en regardant ce qu'ils produisent.
    apports: dict[str, float] = field(default_factory=dict)
    # Ce que les sources ont appris en passant, pour l'explication.
    voisins: int | None = None
    force: float | None = None
    distance: float | None = None
    communs: list[str] = field(default_factory=list)

    def verser(self, source: str, apport: float) -> None:
        """Ajoute un apport. Le plus fort gagne quand une source parle deux
        fois de la même œuvre — deux graines proches ne doivent pas valoir le
        double d'une graine très proche, sinon un profil large écraserait un
        profil précis."""
        if apport > self.apports.get(source, 0.0):
            self.apports[source] = apport

    @property
    def corrobore(self) -> bool:
        """Le contenu ET la communauté désignent-ils cette œuvre ?

        C'est le geste demandé : deux savoirs indépendants qui tombent
        d'accord valent mieux que deux fois le même.
        """
        contenu = self.apports.get("proche", 0.0) + self.apports.get("affinite", 0.0)
        return contenu > 0.0 and self.apports.get("voisins", 0.0) > 0.0

    @property
    def score(self) -> float:
        total = sum(self.apports.values())
        return total * MULTIPLICATEUR_CORROBORATION if self.corrobore else total

    @property
    def source_dominante(self) -> str:
        """La source qui a le plus apporté — celle dont l'explication parle en
        premier."""
        return max(self.apports, key=lambda source: self.apports[source])


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Une œuvre proposée, avec de quoi l'expliquer — le composant l'affiche :
    une suggestion inexpliquée ressemble à de la publicité."""

    oeuvre_id: int
    titre: str | None
    annee: int | None
    affiche: str | None
    univers_interne: str
    # La source dominante : `voisins` la communauté, `proche` l'empreinte,
    # `affinite` les genres et les gens.
    source: str
    # L'identifiant TMDB, nul pour un livre. Donne la clé de vignette, celle
    # que la carte et la fiche attendent.
    id_tmdb: int | None = None
    voisins: int | None = None
    force: float | None = None
    distance: float | None = None
    communs: list[str] = field(default_factory=list)
    # Le contenu et la communauté sont-ils d'accord ? Le front le dit, parce
    # que c'est la suggestion la plus solide qu'on sache produire.
    corrobore: bool = False
    score: float = 0.0

    @property
    def cle_vignette(self) -> int:
        """La clé que la carte et la fiche manipulent : l'identifiant TMDB
        quand il existe, le pivot sinon — la règle de `univers.pivot_card`."""
        return self.id_tmdb if self.id_tmdb is not None else self.oeuvre_id

    @classmethod
    def depuis(cls, candidat: Candidat) -> Suggestion:
        return cls(
            oeuvre_id=candidat.oeuvre_id,
            id_tmdb=candidat.id_tmdb,
            titre=candidat.titre,
            annee=candidat.annee,
            affiche=candidat.affiche,
            univers_interne=candidat.univers_interne,
            source=candidat.source_dominante,
            voisins=candidat.voisins,
            force=candidat.force,
            distance=candidat.distance,
            communs=candidat.communs,
            corrobore=candidat.corrobore,
            score=round(candidat.score, 3),
        )

    def publique(self, slug: str) -> dict[str, Any]:
        return {
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
            "corrobore": self.corrobore,
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


class SourceAffinites:
    """Ce qui partage les genres et les gens des graines, par l'index.

    Le signal le plus faible des trois — partager un genre n'est pas partager
    un goût — mais le seul qui ait toujours de la matière : une œuvre
    collectée a des genres et une distribution, là où être citée par un membre
    ou porter une empreinte notée reste l'exception. Il ne demande pas Neo4j.
    """

    def __init__(self, recherche: Recherche, cartes: Cartes) -> None:
        self._recherche = recherche
        self._cartes = cartes
        self._cles = Cles()

    async def verser(
        self,
        conn: psycopg.AsyncConnection,
        univers: Univers,
        *,
        graines: list[Graine],
        exclues: list[int],
        candidats: dict[int, Candidat],
    ) -> None:
        """Ajoute ses apports aux candidats — en créant ceux qu'elle découvre."""
        pivots = [graine.oeuvre_id for graine in graines]
        cles = await self._cles.vignettes(conn, univers, pivots + exclues)
        semences = [cles[pivot] for pivot in pivots if pivot in cles]
        if not semences:
            return

        documents = await self._recherche.documents(univers, semences)
        if not documents:
            return

        genres = self._retenir(documents, "genres", GENRES_PAR_GRAINE)
        personnes = self._retenir(documents, "personnes", PERSONNES_PAR_GRAINE)
        trouvees = await self._recherche.affinites(
            univers,
            genres=genres,
            personnes=personnes,
            exclus=[cles[pivot] for pivot in exclues if pivot in cles],
            taille=CANDIDATS_PAR_SOURCE,
        )
        if not trouvees:
            return

        # L'hydratation passe par les vignettes, comme la recherche : une
        # seule source de vérité pour ce qui s'affiche.
        cartes = await self._cartes.hydrater(conn, univers, trouvees)
        attendus = set(genres)
        for rang, carte in enumerate(cartes):
            if carte.oeuvre_id is None:
                continue
            candidat = candidats.setdefault(carte.oeuvre_id, Candidat(oeuvre_id=carte.oeuvre_id))
            candidat.id_tmdb = None if univers.pivot_card else carte.id
            candidat.titre = candidat.titre or carte.titre or carte.titre_original
            candidat.annee = candidat.annee if candidat.annee is not None else carte.annee
            candidat.affiche = candidat.affiche or carte.affiche
            candidat.univers_interne = univers.interne
            # Les genres partagés, nommés : c'est ce qui rend la suggestion
            # explicable. Vide quand la correspondance s'est faite sur un nom —
            # on ne l'affirme pas faute de le savoir.
            candidat.communs = [genre for genre in carte.genres if genre in attendus]
            # L'apport décroît avec le rang rendu par ES : le premier résultat
            # ressemble plus aux graines que le soixantième, et l'index le sait
            # mieux que nous. Pas de score brut : il n'est comparable qu'au
            # sein d'une requête, alors qu'on fusionne ici trois échelles.
            decroissance = 1.0 - rang / max(1, len(cartes))
            candidat.verser("affinite", APPORT_AFFINITE * decroissance)

    def _retenir(self, documents: list[dict[str, Any]], champ: str, par_document: int) -> list[str]:
        """Les valeurs les plus fréquentes du champ, dédupliquées.

        Fréquentes d'abord : un genre que trois coups de cœur partagent dit
        mieux le goût qu'un genre vu une fois.
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


class SourceEmpreinte:
    """Les voisins d'ŒUVRE dans l'espace des six axes de goût.

    C'est la source que le lot précédent n'atteignait presque jamais : la
    cascade la plaçait derrière la communauté, qui remplissait la liste. Elle
    a pourtant la propriété qui manquait — elle ne périme pas. Une œuvre notée
    hier est aussi proche d'une graine qu'une œuvre de 2019.
    """

    def __init__(self, graphe: Graphe) -> None:
        self._graphe = graphe

    async def verser(
        self,
        univers: Univers,
        *,
        graines: list[Graine],
        exclues: list[int],
        candidats: dict[int, Candidat],
    ) -> None:
        poids = {graine.oeuvre_id: graine.poids for graine in graines}
        lignes = await self._graphe.executer(
            _CY_PROCHES,
            graines=list(poids),
            candidats=CANDIDATS_VECTEUR,
            univers=univers.interne,
            exclues=exclues,
            limite=CANDIDATS_PAR_SOURCE * 3,
        )
        for ligne in lignes:
            distance = distance_depuis_score(float(ligne["score"]))
            # Au-delà du plafond, l'apport est nul : une œuvre « vaguement du
            # même quadrant » n'a pas à entrer dans la liste par ce chemin.
            if distance >= DISTANCE_MAX:
                continue
            oeuvre_id = ligne["oeuvreId"]
            candidat = candidats.setdefault(oeuvre_id, Candidat(oeuvre_id=oeuvre_id))
            candidat.id_tmdb = candidat.id_tmdb or ligne.get("idTmdb")
            candidat.titre = candidat.titre or ligne.get("titre")
            candidat.annee = candidat.annee if candidat.annee is not None else ligne.get("annee")
            candidat.affiche = candidat.affiche or ligne.get("affiche")
            candidat.univers_interne = ligne.get("univers") or univers.interne
            # L'apport décroît linéairement avec la distance et se pondère par
            # la graine : être à 0,3 point d'une œuvre qu'on a vue et aimée
            # vaut plus qu'être à 0,3 point d'une œuvre qu'on veut voir.
            proximite = 1.0 - distance / DISTANCE_MAX
            candidat.verser(
                "proche", APPORT_EMPREINTE * proximite * poids.get(ligne["graine"], 1.0)
            )
            # La distance affichée est la meilleure trouvée, toutes graines
            # confondues : c'est celle qui explique la présence de l'œuvre.
            if candidat.distance is None or distance < candidat.distance:
                candidat.distance = round(distance, 2)


class SourceCommunaute:
    """Les membres qui citent les graines, et ce qu'ils citent d'autre.

    Le savoir de la V1 — 66 878 positions de tops — et sa limite : **il
    s'arrête en 2019**. Il ne peut donc rien dire d'une œuvre récente, et c'est
    la raison pour laquelle il n'est plus l'étage qui remplit la liste mais une
    source parmi trois. Là où il parle, en revanche, il parle bien : c'est lui
    qui déclenche la corroboration.
    """

    def __init__(self, graphe: Graphe) -> None:
        self._graphe = graphe

    async def verser(
        self,
        univers: Univers,
        *,
        graines: list[Graine],
        exclues: list[int],
        candidats: dict[int, Candidat],
    ) -> None:
        voisins = await self._graphe.executer(
            _CY_VOISINS,
            graines=[graine.oeuvre_id for graine in graines],
            voisinsMax=VOISINS_MAX,
        )
        if not voisins:
            return
        lignes = await self._graphe.executer(
            _CY_CITATIONS_VOISINS,
            voisins=[voisin["membreId"] for voisin in voisins],
            univers=univers.interne,
            exclues=exclues,
            limite=CANDIDATS_PAR_SOURCE,
        )
        if not lignes:
            return
        # Le plus cité sert d'échelle : l'apport est relatif au meilleur de la
        # fournée, jamais un compte brut — dix voisins sur un catalogue de
        # niche ne valent pas dix voisins sur un feuilleton.
        plafond = max(int(ligne["voisins"]) for ligne in lignes) or 1
        for ligne in lignes:
            oeuvre_id = ligne["oeuvreId"]
            candidat = candidats.setdefault(oeuvre_id, Candidat(oeuvre_id=oeuvre_id))
            candidat.id_tmdb = candidat.id_tmdb or ligne.get("idTmdb")
            candidat.titre = candidat.titre or ligne.get("titre")
            candidat.annee = candidat.annee if candidat.annee is not None else ligne.get("annee")
            candidat.affiche = candidat.affiche or ligne.get("affiche")
            candidat.univers_interne = ligne.get("univers") or univers.interne
            candidat.voisins = int(ligne["voisins"])
            force = ligne.get("force")
            candidat.force = round(float(force), 2) if force is not None else None
            # Le nombre de voisins d'abord, leur rang moyen ensuite : une œuvre
            # portée par six membres vaut mieux qu'une portée par un, et une
            # œuvre citée en tête de top vaut mieux que la même citée en queue.
            part_voisins = candidat.voisins / plafond
            part_rang = (candidat.force or 3.0) / 5.0
            candidat.verser("voisins", APPORT_COMMUNAUTE * part_voisins * part_rang)


class Moteur:
    """La fusion des trois sources, et le classement qui en sort.

    C'est le seul objet que la route connaît. Il tient trois promesses :

    * **aucune source ne plafonne les autres** — elles versent toutes leurs
      apports avant qu'on ne classe, là où la cascade laissait la première
      occuper les vingt-quatre places ;
    * **l'accord entre savoirs indépendants gagne** — une œuvre proche par le
      contenu ET portée par la communauté voit son total multiplié ;
    * **une réponse, ou la raison de son absence** — les affinités ne
      demandent ni graphe ni notation, si bien qu'un visiteur qui a classé une
      œuvre collectée obtient toujours quelque chose.
    """

    def __init__(self, recherche: Recherche, cartes: Cartes, graphe: Graphe | None = None) -> None:
        self._graphe = graphe
        self._affinites = SourceAffinites(recherche, cartes)

    def graines(self, pivots_par_statut: dict[str, list[int]]) -> list[Graine]:
        """Les graines pondérées, les plus fortes d'abord et plafonnées.

        `aime_pas` n'en produit aucune : ce qui a été écarté ne décrit pas un
        goût à poursuivre. Il reste exclu des résultats, ce qui est son rôle.
        """
        retenues = [
            Graine(oeuvre_id=pivot, poids=POIDS_STATUT[statut])
            for statut, pivots in pivots_par_statut.items()
            if statut in POIDS_STATUT
            for pivot in pivots
        ]
        retenues.sort(key=lambda graine: -graine.poids)
        return retenues[:GRAINES_MAX]

    async def pour(
        self,
        conn: psycopg.AsyncConnection,
        univers: Univers,
        *,
        pivots_par_statut: dict[str, list[int]],
        limite: int = SUGGESTIONS_MAX,
    ) -> tuple[list[Suggestion], str | None]:
        """La liste classée et, si elle est vide, la raison de l'être."""
        graines = self.graines(pivots_par_statut)
        if not graines:
            return [], "aucun_aime"

        # Tout ce qui est classé est exclu, quel que soit le statut : le connu
        # n'est pas une suggestion, l'écarté ne se repropose pas, et l'envie
        # est déjà une suggestion acceptée.
        exclues = sorted({pivot for pivots in pivots_par_statut.values() for pivot in pivots})

        candidats: dict[int, Candidat] = {}
        if self._graphe is not None:
            empreinte = SourceEmpreinte(self._graphe)
            await empreinte.verser(univers, graines=graines, exclues=exclues, candidats=candidats)
            communaute = SourceCommunaute(self._graphe)
            await communaute.verser(univers, graines=graines, exclues=exclues, candidats=candidats)
        await self._affinites.verser(
            conn, univers, graines=graines, exclues=exclues, candidats=candidats
        )

        retenus = sorted(
            candidats.values(),
            # Le score, puis le pivot : sans ce départage, deux œuvres à
            # égalité changeraient de place d'un appel à l'autre.
            key=lambda candidat: (-candidat.score, candidat.oeuvre_id),
        )
        suggestions = [Suggestion.depuis(candidat) for candidat in retenus[:limite]]
        if suggestions:
            return suggestions, None
        # Rien : la cause est presque toujours la même — les œuvres classées
        # ne sont pas dans l'index de cet univers (jamais collectées, ou
        # `search reindex` pas encore passé).
        return [], "aucun_resultat"
