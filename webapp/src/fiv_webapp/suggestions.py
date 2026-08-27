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

import datetime
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
# rien ne dit encore qu'elles ont plu. Mais l'intention pèse plus qu'avant
# (0,6 contre 0,4) : c'est la seule liste qui parle du goût PRÉSENT du
# visiteur, là où la communauté parle du goût de 2019.
POIDS_STATUT = {"aime": 1.0, "a_voir": 0.6}

# Les graines retenues : un profil se déplace, et soixante coups de cœur
# feraient une requête aussi large que le catalogue.
GRAINES_MAX = 12

# Des places RÉSERVÉES aux envies. Sans elles, douze « vu et aimé »
# évinçaient toutes les « je veux voir » du seul fait de leur poids — et la
# moitié du profil demandé (« ce qu'il a aimé + ce qu'il aimerait voir »)
# n'entrait jamais dans le moteur.
GRAINES_ENVIES_MIN = 4

# --- Les apports des sources ----------------------------------------------
#
# Ils se lisent comme un ordre de confiance : l'empreinte (six axes de goût
# mesurés) au-dessus de la communauté (des gens qui ont aimé les mêmes
# choses), elle-même au-dessus des affinités (un genre, un acteur en commun).
APPORT_EMPREINTE = 1.0
# La communauté est un BONUS, plus un moteur : sa base est figée — dernier
# membre en 2019, dernière œuvre citée avec elle. Un apport qui la laissait
# presque à hauteur de l'empreinte (0,8) suffisait à remplir la liste
# d'œuvres d'avant 2019 dès qu'un classique servait de graine. Elle
# corrobore, elle départage — elle ne conduit plus.
APPORT_COMMUNAUTE = 0.45
APPORT_AFFINITE = 0.55

# --- La convergence : les voisins que PLUSIEURS graines désignent ----------
#
# `verser()` garde le meilleur apport d'une source — deux graines vaguement
# proches ne doivent pas battre une graine très proche. Mais être le voisin
# de TROIS œuvres qu'on a aimées dit plus qu'être le voisin d'une seule :
# c'est l'œuvre vers laquelle le graphe du visiteur converge, celle qui a le
# plus de relations avec ce qu'il aime. Chaque graine au-delà de la première
# ajoute donc une fraction de sa contribution, sous plafond.
BONUS_CONVERGENCE = 0.35
PLAFOND_EMPREINTE = APPORT_EMPREINTE * 1.6

# --- Le profil : les axes du visiteur --------------------------------------
#
# Chaque œuvre notée porte une empreinte — six axes de goût. Le visiteur en a
# une aussi, dès qu'il classe : le CENTRE de ce qu'il aime, POUSSÉ à l'écart
# de ce qu'il rejette. C'est la seule source qui lise les trois listes à la
# fois — « vu et aimé » et « je veux voir » attirent le centre, « j'aime
# pas » le repousse — et elle interroge l'index vectoriel en un seul vecteur,
# là où les voisins de graines en lancent un par œuvre.
APPORT_PROFIL = 0.9
# La force du repoussoir — CALIBRÉE sur la production, pas choisie de tête.
# À 0,5, un profil « Lucifer + Shadowhunters, rejet Pokémon » était expulsé
# hors du nuage (l'axe animation tombait à 1,0) et retombait sur des dramas
# sans rapport ; à 0,15, les voisins restent ceux du goût (Sabrina, Ma
# sorcière bien-aimée) avec l'animation en retrait — l'inflexion voulue,
# sans la fuite. Nul, dire « pas ça » ne servirait à rien.
POIDS_REJET = 0.15

# --- La fraîcheur : du plus récent au plus vieux ---------------------------
#
# Le score final est multiplié par un facteur d'âge. Sans lui, le moteur se
# figeait dans les années de la base communautaire : les graines mènent à des
# voisins de leur époque, la communauté ne connaît rien après 2019, et un
# visiteur au goût actuel recevait un mur d'œuvres anciennes. Le facteur est
# exponentiel avec un PLANCHER : une œuvre ancienne perd la moitié de son
# score, jamais sa place — un chef-d'œuvre de 1994 très proche du profil doit
# encore pouvoir battre une œuvre récente qui ne l'est guère.
FRAICHEUR_PLANCHER = 0.55
FRAICHEUR_CONSTANTE = 12.0
# L'âge prêté à une œuvre sans année : celui d'une œuvre déjà ancienne, ni
# punie au plancher ni hissée parmi les nouveautés qu'elle n'est pas.
FRAICHEUR_AGE_INCONNU = 15

# La corroboration : le multiplicateur appliqué au total d'une œuvre que DEUX
# familles de sources désignent — le contenu (empreinte ou affinités) et la
# communauté. C'est la demande à l'origine de ce lot, et le chiffre est
# volontairement fort : un accord entre deux savoirs indépendants est ce qu'on
# a de plus proche d'une preuve.
MULTIPLICATEUR_CORROBORATION = 1.8

# --- Les plafonds ----------------------------------------------------------

# Le nombre de voisins qu'il faut pour qu'un rapport veuille dire quelque
# chose. Trois : en dessous, la sur-représentation se calcule sur du bruit —
# une œuvre citée par un seul voisin et par un seul membre au monde
# afficherait un rapport énorme sans rien prouver.
VOISINS_MINIMUM = 3

# Le seuil en dessous duquel la communauté se taît : une œuvre citée chez les
# voisins au même taux que partout ne dit rien de vos goûts. 1,2 laisse passer
# ce qui est franchement plus fréquent, pas ce qui l'est marginalement.
SURREPRESENTATION_MINIMUM = 1.2

# Le repère de saturation. Au-delà, « trois fois plus souvent » et « dix fois
# plus souvent » ne se distinguent plus utilement, et les grands rapports sont
# ceux des œuvres rares, donc les moins solides.
SURREPRESENTATION_REPERE = 4.0

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

# La communauté, en UNE traversée : les membres qui citent les graines, ce
# qu'ils citent d'autre, et — c'est le point — la popularité GLOBALE de chaque
# candidat.
#
# Pourquoi cette forme, mesurée sur la production le 26 août 2026. La version
# précédente prenait « les 50 membres qui partagent le plus », puis comptait
# leurs citations. Avec UNE seule graine, tout le monde partage exactement une
# œuvre : l'ordre `communes DESC, membreId` dégénérait en « les 50 plus petits
# identifiants » — un échantillon arbitraire de 4 719 fans, dans le cas de
# Lucifer. Et compter des citations brutes mesure la popularité, pas
# l'affinité : Grey's Anatomy sortait PREMIÈRE, alors qu'elle est citée par
# 7,4 % des fans de Lucifer contre 7,9 % de tous les membres — soit une
# sur-représentation de 0,94, c'est-à-dire une contre-indication.
#
# Deux corrections, donc : tout le voisinage plutôt qu'un échantillon, et un
# classement sur la SUR-REPRÉSENTATION — le taux chez les voisins divisé par
# le taux général. Sur la même graine, ce classement rend Shadow Hunter
# (×2,83), Sabrina (×2,40), Teen Wolf (×2,01) : du surnaturel, ce qu'un
# amateur de Lucifer attend.
#
# `count {}` plutôt qu'un second aller-retour : c'est un décompte de degré,
# que Neo4j lit sans traverser.
_CY_COMMUNAUTE = """
MATCH (s:FivOeuvre) WHERE s.oeuvreId IN $graines
MATCH (s)<-[:FIV_CITE]-(v:FivMembre)
WITH collect(DISTINCT v) AS voisinage
WITH voisinage, size(voisinage) AS taille
UNWIND voisinage AS voisin
MATCH (voisin)-[c:FIV_CITE]->(reco:FivOeuvre)
WHERE reco.univers = $univers AND NOT reco.oeuvreId IN $exclues
WITH reco, taille, count(DISTINCT voisin) AS voisins, avg(6 - coalesce(c.rang, 5)) AS force
WHERE voisins >= $minimum
WITH reco, taille, voisins, force,
     count { (reco)<-[:FIV_CITE]-(:FivMembre) } AS citations
RETURN reco.oeuvreId AS oeuvreId, reco.idTmdb AS idTmdb, reco.titre AS titre,
       reco.annee AS annee, reco.affiche AS affiche, reco.univers AS univers,
       voisins, force, citations, taille
ORDER BY (1.0 * voisins / taille) / (1.0 * citations / $membres) DESC, voisins DESC
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


# Les empreintes d'une liste d'œuvres — la matière du profil.
_CY_EMPREINTES = """
MATCH (s:FivOeuvre) WHERE s.oeuvreId IN $pivots AND s.empreinte IS NOT NULL
RETURN s.oeuvreId AS oeuvreId, s.empreinte AS empreinte
"""

# Les voisins du PROFIL : une seule interrogation de l'index vectoriel, sur
# le vecteur du visiteur plutôt que sur chaque graine.
_CY_PROFIL = """
CALL db.index.vector.queryNodes('fivEmpreinteVoisins', $candidats, $profil)
YIELD node, score
WHERE node.univers = $univers AND NOT node.oeuvreId IN $exclues
RETURN node.oeuvreId AS oeuvreId, node.idTmdb AS idTmdb, node.titre AS titre,
       node.annee AS annee, node.affiche AS affiche, node.univers AS univers, score
ORDER BY score DESC
LIMIT $limite
"""


def profil_depuis(
    positives: list[tuple[list[float], float]], rejets: list[list[float]]
) -> list[float] | None:
    """Le vecteur du visiteur sur les six axes.

    Le centre PONDÉRÉ des empreintes aimées et voulues (un verdict pèse plus
    qu'une envie), poussé à l'écart du centre des rejets : `« j'aime pas »`
    cesse d'être un simple filtre — il déplace le profil, comme demandé.

    Rend `None` sans matière positive : un profil fait uniquement de rejets
    ne pointe nulle part.
    """
    portees = [(empreinte, poids) for empreinte, poids in positives if empreinte]
    if not portees:
        return None
    axes = len(portees[0][0])
    total = sum(poids for _, poids in portees)
    centre = [
        sum(empreinte[i] * poids for empreinte, poids in portees) / total for i in range(axes)
    ]
    utiles = [empreinte for empreinte in rejets if len(empreinte) == axes]
    if not utiles:
        return centre
    repoussoir = [sum(empreinte[i] for empreinte in utiles) / len(utiles) for i in range(axes)]
    return [centre[i] + POIDS_REJET * (centre[i] - repoussoir[i]) for i in range(axes)]


def facteur_fraicheur(annee: int | None, courante: int | None = None) -> float:
    """Le poids d'une œuvre selon son âge — 1,0 cette année, le plancher pour
    les très anciennes.

    C'est lui qui ordonne la liste « du plus récent au plus vieux » sans en
    faire un tri aveugle : la pertinence compte toujours, l'âge la module.
    """
    courante = courante if courante is not None else datetime.date.today().year
    age = FRAICHEUR_AGE_INCONNU if annee is None else max(0, courante - annee)
    return FRAICHEUR_PLANCHER + (1.0 - FRAICHEUR_PLANCHER) * math.exp(-age / FRAICHEUR_CONSTANTE)


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
    # Combien de fois plus souvent les voisins citent cette œuvre que la base
    # entière. C'est ce qui distingue un signal d'une popularité.
    surrepresentation: float | None = None
    # Combien de graines DISTINCTES ont désigné cette œuvre comme voisine :
    # au-delà de une, c'est l'œuvre vers laquelle le graphe du visiteur
    # converge, et l'explication le dit.
    convergences: int | None = None
    # Les genres de la vignette, attachés à l'hydratation finale : le front
    # en fait ses puces d'exclusion (« moins de dessins animés »).
    genres: list[str] = field(default_factory=list)

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
        contenu = (
            self.apports.get("proche", 0.0)
            + self.apports.get("profil", 0.0)
            + self.apports.get("affinite", 0.0)
        )
        return contenu > 0.0 and self.apports.get("voisins", 0.0) > 0.0

    @property
    def score(self) -> float:
        """Le total des apports, corroboration comprise, MODULÉ par l'âge.

        La fraîcheur s'applique au total et non à une source : la communauté,
        figée en 2019, ne propose que de l'ancien — c'est précisément elle que
        le facteur ramène derrière les voisins d'empreinte récents.
        """
        total = sum(self.apports.values())
        if self.corrobore:
            total *= MULTIPLICATEUR_CORROBORATION
        return total * facteur_fraicheur(self.annee)

    @property
    def retenu(self) -> bool:
        """A-t-il reçu le moindre apport ?

        Un candidat peut être CRÉÉ sans en recevoir : la communauté note ce
        qu'elle sait d'une œuvre (titre, affiche, voisins) puis se taît si
        elle est sous-représentée — l'œuvre reste alors candidate pour une
        source de contenu, mais n'est pas une suggestion en soi. Sans ce
        garde-fou, une telle carte partait au classement sans score, et
        `source_dominante` tombait sur un `max()` vide.
        """
        return bool(self.apports)

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
    surrepresentation: float | None = None
    convergences: int | None = None
    genres: list[str] = field(default_factory=list)
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
            surrepresentation=candidat.surrepresentation,
            convergences=candidat.convergences,
            genres=candidat.genres,
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
            "surrepresentation": self.surrepresentation,
            "convergences": self.convergences,
            "genres": self.genres,
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
        # Les contributions s'ACCUMULENT par candidat avant de verser : c'est
        # ce qui permet la convergence — être le voisin de trois graines dit
        # plus qu'être le voisin d'une seule, et `verser()` seul, qui garde le
        # max, ne pouvait pas le voir.
        contributions: dict[int, dict[int, float]] = {}
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
            # La contribution décroît linéairement avec la distance et se
            # pondère par la graine : être à 0,3 point d'une œuvre qu'on a vue
            # et aimée vaut plus qu'être à 0,3 point d'une œuvre qu'on veut
            # voir. Par graine, on garde la meilleure — une graine ne converge
            # pas avec elle-même.
            proximite = 1.0 - distance / DISTANCE_MAX
            contribution = APPORT_EMPREINTE * proximite * poids.get(ligne["graine"], 1.0)
            par_graine = contributions.setdefault(oeuvre_id, {})
            graine = int(ligne["graine"])
            par_graine[graine] = max(par_graine.get(graine, 0.0), contribution)
            # La distance affichée est la meilleure trouvée, toutes graines
            # confondues : c'est celle qui explique la présence de l'œuvre.
            if candidat.distance is None or distance < candidat.distance:
                candidat.distance = round(distance, 2)

        for oeuvre_id, par_graine in contributions.items():
            classees = sorted(par_graine.values(), reverse=True)
            # La meilleure graine donne la base ; chaque graine SUPPLÉMENTAIRE
            # ajoute une fraction de sa propre contribution, sous plafond —
            # un profil large ne doit pas écraser un profil précis, mais une
            # œuvre vers laquelle tout le profil converge doit monter.
            apport = classees[0] + BONUS_CONVERGENCE * sum(classees[1:])
            candidat = candidats[oeuvre_id]
            candidat.convergences = len(classees)
            candidat.verser("proche", min(apport, PLAFOND_EMPREINTE))


class SourceProfil:
    """Les voisins des AXES du visiteur — son profil, pas ses œuvres une à une.

    Ce que cette source voit et que `SourceEmpreinte` ne voit pas : le centre.
    Les voisins de graines rapprochent de CHAQUE œuvre aimée ; le profil
    rapproche de leur barycentre — et il est le seul endroit où « j'aime
    pas » travaille, en repoussant ce centre au lieu de seulement filtrer.
    """

    def __init__(self, graphe: Graphe) -> None:
        self._graphe = graphe

    async def verser(
        self,
        univers: Univers,
        *,
        graines: list[Graine],
        rejets: list[int],
        exclues: list[int],
        candidats: dict[int, Candidat],
    ) -> None:
        pivots = [graine.oeuvre_id for graine in graines] + rejets
        lignes = await self._graphe.executer(_CY_EMPREINTES, pivots=pivots)
        empreintes = {ligne["oeuvreId"]: ligne["empreinte"] for ligne in lignes}
        poids = {graine.oeuvre_id: graine.poids for graine in graines}
        profil = profil_depuis(
            [(empreintes[pivot], poids[pivot]) for pivot in poids if empreintes.get(pivot)],
            [empreintes[pivot] for pivot in rejets if empreintes.get(pivot)],
        )
        if profil is None:
            return

        lignes = await self._graphe.executer(
            _CY_PROFIL,
            profil=profil,
            candidats=CANDIDATS_PAR_SOURCE,
            univers=univers.interne,
            exclues=exclues,
            limite=CANDIDATS_PAR_SOURCE,
        )
        for ligne in lignes:
            distance = distance_depuis_score(float(ligne["score"]))
            if distance >= DISTANCE_MAX:
                continue
            oeuvre_id = ligne["oeuvreId"]
            candidat = candidats.setdefault(oeuvre_id, Candidat(oeuvre_id=oeuvre_id))
            candidat.id_tmdb = candidat.id_tmdb or ligne.get("idTmdb")
            candidat.titre = candidat.titre or ligne.get("titre")
            candidat.annee = candidat.annee if candidat.annee is not None else ligne.get("annee")
            candidat.affiche = candidat.affiche or ligne.get("affiche")
            candidat.univers_interne = ligne.get("univers") or univers.interne
            proximite = 1.0 - distance / DISTANCE_MAX
            candidat.verser("profil", APPORT_PROFIL * proximite)
            if candidat.distance is None or distance < candidat.distance:
                candidat.distance = round(distance, 2)


class SourceCommunaute:
    """Les membres qui citent les graines, et ce qu'ils citent d'autre.

    Le savoir de la V1 — 66 878 positions de tops, 58 409 membres — et ses
    deux limites, dont une mesurée le 26 août 2026 sur la production :

    * **il s'arrête en 2019** : il ne peut rien dire d'une œuvre récente, ce
      qui lui a valu de n'être plus l'étage qui remplit la liste ;
    * **compter des citations brutes mesure la popularité, pas l'affinité.**
      Grey's Anatomy sortait première sur une graine « Lucifer », alors
      qu'elle est citée par 7,4 % des fans de Lucifer contre 7,9 % de tous
      les membres. La série la plus citée d'une base remonte quelle que soit
      la graine, et une contre-indication passait pour une recommandation.

    D'où le classement par **sur-représentation** : le taux chez les voisins
    divisé par le taux général. Un plancher de voisins l'accompagne, parce
    qu'un rapport calculé sur deux citations ne mesure rien.
    """

    def __init__(self, graphe: Graphe) -> None:
        self._graphe = graphe
        self._membres: int | None = None

    async def _total_membres(self) -> int:
        """Le nombre de membres du graphe, lu une fois par instance.

        Il sert de dénominateur au taux général. Une valeur figée dans le code
        périmerait au premier import de membres ; un décompte par requête de
        suggestion serait un balayage de label de trop.
        """
        if self._membres is None:
            lignes = await self._graphe.executer("MATCH (m:FivMembre) RETURN count(m) AS total")
            self._membres = int(lignes[0]["total"]) if lignes else 1
        return max(1, self._membres)

    async def verser(
        self,
        univers: Univers,
        *,
        graines: list[Graine],
        exclues: list[int],
        candidats: dict[int, Candidat],
    ) -> None:
        membres = await self._total_membres()
        lignes = await self._graphe.executer(
            _CY_COMMUNAUTE,
            graines=[graine.oeuvre_id for graine in graines],
            univers=univers.interne,
            exclues=exclues,
            minimum=VOISINS_MINIMUM,
            membres=membres,
            limite=CANDIDATS_PAR_SOURCE,
        )
        if not lignes:
            return
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

            taille = max(1, int(ligne["taille"]))
            citations = max(1, int(ligne["citations"]))
            # La sur-représentation : combien de fois plus souvent cette œuvre
            # est citée chez les voisins que dans la base entière. 1,0 = pas
            # de signal, en dessous = une contre-indication.
            surrepresentation = (candidat.voisins / taille) / (citations / membres)
            candidat.surrepresentation = round(surrepresentation, 2)
            # En dessous du seuil, l'apport est nul : l'œuvre est là parce
            # qu'elle est populaire, pas parce qu'elle vous ressemble. Elle
            # reste candidate si une source de CONTENU la porte.
            if surrepresentation < SURREPRESENTATION_MINIMUM:
                continue
            # L'apport croît avec la sur-représentation, en saturant : au-delà
            # du repère, « beaucoup plus souvent » ne se distingue plus utilement
            # de « énormément plus souvent », et un rapport calculé sur peu de
            # citations est bruité.
            confiance = min(
                1.0,
                math.log(1 + surrepresentation) / math.log(1 + SURREPRESENTATION_REPERE),
            )
            part_rang = (candidat.force or 3.0) / 5.0
            candidat.verser("voisins", APPORT_COMMUNAUTE * confiance * part_rang)


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
        self._cartes = cartes
        self._affinites = SourceAffinites(recherche, cartes)

    def graines(self, pivots_par_statut: dict[str, list[int]]) -> list[Graine]:
        """Les graines pondérées et plafonnées — avec des places RÉSERVÉES aux
        envies.

        Le profil demandé est « ce qu'il a vu et aimé + ce qu'il aimerait
        voir ». Or un simple tri par poids donnait toutes les places aux
        « aimé » dès qu'il y en avait douze, et les envies — la seule liste
        qui parle du goût présent — n'entraient jamais. Les « aimé » gardent
        la priorité, mais jamais toute la table.

        `aime_pas` n'en produit aucune : ce qui a été écarté ne décrit pas un
        goût à poursuivre. Il reste exclu des résultats, ce qui est son rôle.
        """
        aimes = [
            Graine(oeuvre_id=pivot, poids=POIDS_STATUT["aime"])
            for pivot in pivots_par_statut.get("aime", [])
        ]
        envies = [
            Graine(oeuvre_id=pivot, poids=POIDS_STATUT["a_voir"])
            for pivot in pivots_par_statut.get("a_voir", [])
        ]
        places_envies = min(len(envies), GRAINES_ENVIES_MIN)
        retenues = aimes[: GRAINES_MAX - places_envies] + envies
        retenues.sort(key=lambda graine: -graine.poids)
        return retenues[:GRAINES_MAX]

    async def pour(
        self,
        conn: psycopg.AsyncConnection,
        univers: Univers,
        *,
        pivots_par_statut: dict[str, list[int]],
        limite: int = SUGGESTIONS_MAX,
        sans_genres: list[str] | None = None,
    ) -> tuple[list[Suggestion], str | None]:
        """La liste classée et, si elle est vide, la raison de l'être.

        `sans_genres` écarte les genres que le visiteur a masqués (« moins de
        dessins animés ») — un filtre de présentation, pas un signal de goût :
        il ne touche ni les graines ni les scores, il retire de la table.
        """
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
            profil = SourceProfil(self._graphe)
            await profil.verser(
                univers,
                graines=graines,
                rejets=pivots_par_statut.get("aime_pas", []),
                exclues=exclues,
                candidats=candidats,
            )
            communaute = SourceCommunaute(self._graphe)
            await communaute.verser(univers, graines=graines, exclues=exclues, candidats=candidats)
        await self._affinites.verser(
            conn, univers, graines=graines, exclues=exclues, candidats=candidats
        )

        retenus = sorted(
            (candidat for candidat in candidats.values() if candidat.retenu),
            # Le score (fraîcheur comprise), puis l'année la plus récente,
            # puis le pivot : sans départage, deux œuvres à égalité
            # changeraient de place d'un appel à l'autre.
            key=lambda candidat: (-candidat.score, -(candidat.annee or 0), candidat.oeuvre_id),
        )
        # L'hydratation des GENRES sur la tête de liste, avant la coupe : le
        # front en fait ses puces d'exclusion, et le filtre « sans » se joue
        # ici — élargi à trois pages pour que masquer un genre ne rende pas
        # une liste courte.
        tete = retenus[: limite * 3]
        genres_connus = await self._genres_de(conn, univers, tete)
        for candidat in tete:
            cle = candidat.id_tmdb if candidat.id_tmdb is not None else candidat.oeuvre_id
            candidat.genres = genres_connus.get(cle, [])
        if sans_genres:
            ecartes = {genre.strip().casefold() for genre in sans_genres if genre.strip()}
            tete = [
                candidat
                for candidat in tete
                if not ecartes & {genre.casefold() for genre in candidat.genres}
            ]

        suggestions = [Suggestion.depuis(candidat) for candidat in tete[:limite]]
        if suggestions:
            return suggestions, None
        # Rien : la cause est presque toujours la même — les œuvres classées
        # ne sont pas dans l'index de cet univers (jamais collectées, ou
        # `search reindex` pas encore passé).
        return [], "aucun_resultat"

    async def _genres_de(
        self, conn: psycopg.AsyncConnection, univers: Univers, candidats: list[Candidat]
    ) -> dict[int, list[str]]:
        """Les genres de chaque candidat, par clé de vignette.

        Une seule requête sur les projections, et une tolérance : un candidat
        que l'hydratation ne connaît pas garde une liste vide — il reste
        proposé, et simplement infiltrables par genre.
        """
        cles = [
            candidat.id_tmdb if candidat.id_tmdb is not None else candidat.oeuvre_id
            for candidat in candidats
        ]
        if not cles:
            return {}
        hydratees = await self._cartes.hydrater(conn, univers, cles)
        return {carte.id: carte.genres for carte in hydratees}
