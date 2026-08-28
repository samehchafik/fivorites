"""Le graphe Neo4j : les œuvres, leurs genres, leurs gens, leur empreinte.

C'est la phase 1 de [`doc/plan-apres-notation.md`](../../../doc/plan-apres-notation.md)
— « livrer, plutôt qu'améliorer ». La notation existe, l'inventaire existe ;
il manquait l'espace où l'un rencontre l'autre. Le raisonnement de modélisation
complet est dans [`doc/graphe-neo4j.md`](../../../doc/graphe-neo4j.md) ; ici,
seulement ce qu'il faut pour lire le code.

**Tout est préfixé `Fiv`.** Labels (`FivOeuvre`) et types de relation
(`FIV_A_POUR_GENRE`). Neo4j n'a pas de schémas comme Postgres : une base
héberge un seul espace de noms, et le préfixe est le seul moyen de dire « ceci
est à nous ». Le jour où la même instance porte un import tiers, un plugin ou
une expérimentation, rien ne se mélange et `MATCH (n:FivOeuvre)` reste exact.

**L'univers est un label, pas une relation.** `(:FivOeuvre:FivFilm)` plutôt que
`(:FivOeuvre)-[:FIV_EST_UN]->(:FivUnivers {nom:'film'})`. Un nœud d'univers
serait un supernœud — un million de relations entrantes — traversé par toutes
les requêtes et utile à aucune : personne ne demande « les autres films », qui
est le catalogue entier. Les labels, eux, sont l'outil natif de Neo4j pour
exactement ça : un balayage par label est une opération de premier ordre, et
`MATCH (o:FivOeuvre:FivFilm)` ne coûte rien. Le genre, lui, est bien une
relation : « les autres drames » est une question qu'on pose vraiment.
`univers` reste aussi une propriété — le label sert au moteur, la propriété
sert à la lecture et au retour vers Postgres.

**L'empreinte est portée deux fois, et c'est délibéré.** `empreinte` est le
vecteur brut (les notes de 1 à 10, dans l'ordre des axes du barème) ;
`empreinteUnitaire` est le même, ramené à la norme 1. Deux index vectoriels en
découlent, parce qu'ils ne répondent pas à la même question :

* `fivEmpreinteVoisins` (euclidien, sur `empreinte`) — « le plus proche », au
  sens GPS. La distance s'y lit en points de note, donc elle se compare
  directement au MAE de 0,84 du système : deux œuvres plus proches que ça sont
  indiscernables, et le dire est plus utile qu'un score sans unité.
* `fivEmpreinteCouleur` (cosinus, sur `empreinteUnitaire`) — la *forme* de
  l'empreinte, intensité mise de côté. C'est la métrique décidée au §5.1 de
  `doc/mission-empreinte-culturelle.md`, et c'est elle que le profil d'un
  membre interrogera.

Le §5.4 du même document notait la limite du cosinus — « deux œuvres de même
couleur mais d'intensité différente auront une similarité de 1 [...] il faudra
réintroduire la norme comme critère secondaire, et c'est une décision à prendre
consciemment plutôt qu'à découvrir ». `empreinteNorme` est cette décision,
prise : elle est sur le nœud, filtrable et triable.

Le transport est HTTP (Query API v2), pas Bolt, et sans le pilote officiel —
même choix que pour Elasticsearch dans `search.py`, qui parle à ES en httpx
sans client dédié. Une dépendance de moins dans l'image, et le protocole reste
lisible dans les journaux.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fiv_admin.media import Media

log = logging.getLogger(__name__)

SOURCE = "tmdb"

# ---------------------------------------------------------------------------
# Le vocabulaire du graphe. Rien de ce qui suit n'est écrit ailleurs en dur :
# renommer une relation se fait ici, et le schéma comme la projection suivent.

PREFIXE = "Fiv"

LABEL_OEUVRE = "FivOeuvre"
LABEL_GENRE = "FivGenre"
LABEL_PERSONNE = "FivPersonne"

# Le membre du site, et il n'a rien à voir avec `:FivPersonne` — qui est
# l'acteur, le réalisateur, le créateur. Deux populations, deux labels : le
# jour où un membre est aussi un réalisateur, ce sont deux nœuds, et c'est
# juste. Confondre les deux ferait apparaître un abonné dans un générique.
#
# LE NŒUD EST ANONYME, et c'est la décision qui porte tout le reste. Il ne
# transporte que `membreId` — l'identifiant interne de `membre.membre`. Ni
# pseudo, ni email, ni identifiant V1. Le voisinage n'en a pas besoin : deux
# membres qui citent la même œuvre sont voisins, qu'on sache leur nom ou non.
# Et ce qu'un graphe ne porte pas ne peut fuiter par aucune requête.
LABEL_MEMBRE = "FivMembre"

# Les métiers, en labels supplémentaires sur le MÊME nœud.
#
# `:FivPersonne:FivActeur:FivRealisateur` plutôt que deux nœuds : Clint
# Eastwood joue et réalise, souvent dans le même film. Deux nœuds le
# dédoubleraient — donc deux fiches, deux filmographies, et « le réalisateur
# qui joue dans ses films » deviendrait une question sans réponse.
#
# Le label est ce que Neo4j offre exactement pour ça : `MATCH (a:FivActeur)`
# est un balayage de premier ordre, et un nœud peut en porter plusieurs. Même
# raisonnement qu'`:FivOeuvre:FivFilm` (§2.1 du doc) — le métier n'est pas une
# entité à part, c'est une facette de la personne.
#
# `:FivPersonne` reste et porte l'identité : c'est lui que la contrainte
# d'unicité vise, et c'est sur lui que tous les `MERGE` s'ancrent. Les autres
# se posent par-dessus.
LABEL_ACTEUR = "FivActeur"
LABEL_REALISATEUR = "FivRealisateur"
LABEL_CREATEUR = "FivCreateur"

# Le métier que chaque relation confère à la personne qui la porte. C'est aussi
# la table qui dit à `elaguer` quel label retirer quand la dernière relation
# d'un métier disparaît.
LABEL_DU_ROLE: dict[str, str] = {
    "FIV_JOUE_DANS": LABEL_ACTEUR,
    "FIV_A_REALISE": LABEL_REALISATEUR,
    "FIV_A_CREE": LABEL_CREATEUR,
}

# Le point de reprise de la synchronisation, rangé DANS le graphe : il meurt
# avec lui, et un graphe reconstruit repart donc de son propre début. Aucun
# état à tenir ailleurs — même principe que le marqueur `_meta` d'ES.
LABEL_ETAT = "FivEtat"

# Le second label d'une œuvre, celui qui dit son univers. `books`, `bd` et
# `musics` viendront s'ajouter ici — et nulle part ailleurs.
LABEL_UNIVERS: dict[str, str] = {
    "series": "FivSerie",
    "movies": "FivFilm",
    "livres": "FivLivre",
}

REL_GENRE = "FIV_A_POUR_GENRE"
# « Ce membre a mis cette œuvre dans un de ses tops », et le rang est porté par
# la relation : la première place n'est pas la cinquième, c'est le seul degré
# de force que la V1 nous donne.
REL_CITE = "FIV_CITE"
REL_JOUE = "FIV_JOUE_DANS"
REL_REALISE = "FIV_A_REALISE"
REL_CREE = "FIV_A_CREE"

# Les relations que la projection possède, donc celles qu'elle a le droit
# d'effacer avant de les réécrire. Une relation posée à la main (ou par un lot
# futur) qui ne figure pas ici survit à une reprojection.
RELATIONS_PROJETEES = (REL_GENRE, REL_JOUE, REL_REALISE, REL_CREE)

INDEX_VOISINS = "fivEmpreinteVoisins"
INDEX_COULEUR = "fivEmpreinteCouleur"

# Les personnes retenues par œuvre.
#
# TMDB rend la distribution dans l'ordre du générique (`order`), et la queue en
# est le figurant crédité d'une réplique. Au-delà d'une quinzaine, on n'ajoute
# pas de signal : on fabrique des supernœuds — un acteur de complément relie
# entre elles des centaines d'œuvres qui n'ont rien à voir, et chaque
# traversée par les personnes doit ensuite les écarter.
DISTRIBUTION_MAX = 15

# Les réalisateurs retenus, pour une série seulement.
#
# Un film a UN réalisateur (parfois deux). Une série de trois cents épisodes en
# a quatre-vingts, dont soixante ont dirigé un unique épisode : c'est du bruit,
# et c'est le créateur qui porte le signal — d'où `FIV_A_CREE`, qui n'existe
# que pour les séries. On garde les réalisateurs les plus présents, par nombre
# d'épisodes décroissant.
REALISATEURS_MAX = 10


# ---------------------------------------------------------------------------
# Le schéma
# ---------------------------------------------------------------------------


def schema_cypher(dimensions: int) -> tuple[str, ...]:
    """Les instructions de schéma, prêtes à exécuter dans l'ordre.

    `dimensions` est le nombre d'axes du barème courant, pas une constante :
    c'est le barème qui définit l'espace, et un barème à sept axes n'est pas
    une variante du précédent, c'est un autre espace. Les index vectoriels
    portent donc la dimension du barème sous lequel ils sont posés, et Neo4j
    refuse d'indexer un vecteur d'une autre taille — ce qui est exactement le
    garde-fou qu'on veut : le désaccord se voit à l'écriture, pas dans un
    classement silencieusement faux.

    Tout est `IF NOT EXISTS` : la commande se rejoue sans dommage.
    """
    return (
        # L'identité. `oeuvreId` est le pivot `sourcing.oeuvre.id` — jamais
        # l'identifiant TMDB, qui ne désigne pas la même œuvre selon l'univers
        # et qui manque à 300 des 480 séries de langue arabe.
        f"CREATE CONSTRAINT fivOeuvreCle IF NOT EXISTS"
        f" FOR (o:{LABEL_OEUVRE}) REQUIRE o.oeuvreId IS UNIQUE",
        # Genres et personnes n'ont pas encore de pivot en Postgres : leur clé
        # est l'identifiant de la source, préfixé par elle. `tmdb:18`, et non
        # `18`, parce que le jour où un genre vient de Wikidata ou d'un
        # référentiel de livres, les deux espaces de numéros se croiseraient.
        f"CREATE CONSTRAINT fivGenreCle IF NOT EXISTS"
        f" FOR (g:{LABEL_GENRE}) REQUIRE g.cle IS UNIQUE",
        f"CREATE CONSTRAINT fivPersonneCle IF NOT EXISTS"
        f" FOR (p:{LABEL_PERSONNE}) REQUIRE p.cle IS UNIQUE",
        # Le membre. Sa clé est l'identifiant interne, jamais le `v1_id` : ce
        # dernier est un identifiant de l'ancien site, et le graphe n'a aucune
        # raison de porter un pont vers lui.
        f"CREATE CONSTRAINT fivMembreCle IF NOT EXISTS"
        f" FOR (m:{LABEL_MEMBRE}) REQUIRE m.membreId IS UNIQUE",
        # Un marqueur par univers, et un seul : deux marqueurs concurrents
        # feraient repartir la synchronisation du plus ancien, donc rejouer
        # sans fin, ou du plus récent, donc creuser un trou.
        f"CREATE CONSTRAINT fivEtatCle IF NOT EXISTS"
        f" FOR (e:{LABEL_ETAT}) REQUIRE e.univers IS UNIQUE",
        # Le chemin de retour vers le reste du système : une route d'API ou une
        # page d'admin tient un identifiant TMDB et un univers, pas un pivot.
        f"CREATE INDEX fivOeuvreTmdb IF NOT EXISTS FOR (o:{LABEL_OEUVRE}) ON (o.univers, o.idTmdb)",
        f"CREATE INDEX fivPersonneNom IF NOT EXISTS FOR (p:{LABEL_PERSONNE}) ON (p.nom)",
        # « Le plus proche », au sens GPS : la distance euclidienne dans
        # l'espace des axes. Neo4j rend un score borné 0..1 valant 1/(1+d²) ;
        # la distance se retrouve donc par `sqrt(1/score - 1)`, et elle est en
        # points de note — la même unité que le MAE de 0,84 du système.
        f"CREATE VECTOR INDEX {INDEX_VOISINS} IF NOT EXISTS"
        f" FOR (o:{LABEL_OEUVRE}) ON (o.empreinte)"
        f" OPTIONS {{ indexConfig: {{"
        f" `vector.dimensions`: {dimensions},"
        f" `vector.similarity_function`: 'euclidean',"
        # La quantification est ACTIVE par défaut (`'scalar'`). Elle est faite
        # pour des embeddings de 1 536 dimensions qu'on veut faire tenir en
        # mémoire ; ici le vecteur en a six. Il n'y a rien à économiser, et
        # arrondir six nombres qui portent tout le sens du classement, c'est
        # payer une perte de précision contre rien.
        f" `vector.quantization.type`: 'none'"
        f" }} }}",
        # La couleur : le cosinus, sur le vecteur ramené à la norme 1. Cosinus
        # sur le vecteur unitaire et cosinus sur le vecteur brut donnent le
        # même classement — la propriété séparée n'existe que parce qu'un index
        # vectoriel ne porte qu'une métrique, et qu'on en veut deux.
        f"CREATE VECTOR INDEX {INDEX_COULEUR} IF NOT EXISTS"
        f" FOR (o:{LABEL_OEUVRE}) ON (o.empreinteUnitaire)"
        f" OPTIONS {{ indexConfig: {{"
        f" `vector.dimensions`: {dimensions},"
        f" `vector.similarity_function`: 'cosine',"
        f" `vector.quantization.type`: 'none'"
        f" }} }}",
    )


# ---------------------------------------------------------------------------
# Le transport
# ---------------------------------------------------------------------------


class GrapheErreur(RuntimeError):
    """Neo4j a refusé une instruction. Le message porte le code Neo4j, qui est
    la seule chose exploitable pour trier une erreur de schéma d'une erreur de
    données."""


# La Query API refuse les retours à la ligne littéraux dans un `statement` :
# c'est du JSON, et le Cypher doit tenir sur une ligne. Cypher lit un saut de
# ligne comme une espace, la conversion est donc sans effet de bord — à une
# exception près, les commentaires `//`, qui avaleraient le reste de
# l'instruction une fois tout mis bout à bout. On les retire avant de plier.
_COMMENTAIRE = re.compile(r"^\s*//.*$", re.MULTILINE)


def une_ligne(cypher: str) -> str:
    """Une instruction Cypher, pliée sur une ligne pour la Query API."""
    return " ".join(_COMMENTAIRE.sub("", cypher).split())


class Graphe:
    """Un client Neo4j minimal, par la Query API v2.

    Volontairement sans transaction explicite : chaque requête est enveloppée
    par le serveur dans sa propre transaction, ce qui est le bon grain pour une
    projection par lots — un lot passe ou ne passe pas, et la reprise consiste
    à relancer la commande, qui est idempotente.
    """

    def __init__(
        self,
        url: str,
        utilisateur: str,
        mot_de_passe: str,
        *,
        base: str = "neo4j",
        timeout: float = 30.0,
    ) -> None:
        self._chemin = f"/db/{base}/query/v2"
        self._http = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            auth=(utilisateur, mot_de_passe),
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> Graphe:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.fermer()

    async def fermer(self) -> None:
        await self._http.aclose()

    async def executer(self, cypher: str, **parametres: Any) -> list[dict[str, Any]]:
        """Une instruction, ses paramètres, ses lignes de résultat.

        Les paramètres passent par `parameters` et jamais par interpolation :
        Neo4j met en cache le plan d'exécution par forme de requête, et une
        projection qui recompilerait à chaque lot perdrait l'essentiel de son
        temps dans le planificateur.
        """
        reponse = await self._http.post(
            self._chemin,
            json={"statement": une_ligne(cypher), "parameters": parametres},
        )
        if reponse.status_code == 401:
            raise GrapheErreur(
                "Neo4j refuse l'authentification — vérifier NEO4J_USER / NEO4J_PASSWORD"
            )
        corps = reponse.json()
        erreurs = corps.get("errors")
        if erreurs:
            premiere = erreurs[0]
            raise GrapheErreur(f"{premiere.get('code')} : {premiere.get('message')}")
        reponse.raise_for_status()
        donnees = corps.get("data") or {}
        champs: list[str] = donnees.get("fields") or []
        return [dict(zip(champs, ligne, strict=False)) for ligne in donnees.get("values") or []]


# ---------------------------------------------------------------------------
# L'extraction : Postgres → une ligne par œuvre
# ---------------------------------------------------------------------------

# Le barème courant : le plus récent, la même règle que partout ailleurs (voir
# `catalog.BAREME_COURANT`). Les notes des barèmes précédents restent en base
# mais n'entrent pas dans le graphe : deux référentiels n'ont pas les mêmes
# axes, et les mélanger fabriquerait un vecteur qui n'existe dans aucun des
# deux.
_EXTRACTION = sql.SQL(
    """
    with bareme as (
        select version, axes from notation.rubric order by created_at desc limit 1
    ),
    -- L'ordre des axes du barème EST l'ordre des coordonnées du vecteur. Il ne
    -- se devine pas et ne se trie pas alphabétiquement : il se lit ici.
    axe as (
        select rang::int as rang, valeur as nom
        from bareme, jsonb_array_elements_text(bareme.axes) with ordinality as t(valeur, rang)
    ),
    oeuvres as (
        select o.id, o.id_tmdb, o.titre, o.annee
        from oeuvre o
        where o.univers = %(univers)s
          -- `ids` nul = tout l'univers ; sinon les seuls pivots listés.
          and (%(ids)s::bigint[] is null or o.id = any (%(ids)s))
    ),
    -- La dernière note par (œuvre, axe), tenue séparément pour le juge et pour
    -- la régression interne. Les deux populations ne se mélangent jamais dans
    -- un même vecteur : la ridge contracte vers la moyenne (pente mesurée de
    -- 0,49 à 0,68), et un vecteur moitié jugé moitié prédit aurait des
    -- coordonnées d'amplitudes incomparables.
    notes as (
        select distinct on (s.oeuvre_id, s.axe, s.modele = 'interne-ridge')
               s.oeuvre_id, s.axe, s.valeur,
               (s.modele = 'interne-ridge') as interne
        from notation.score s
        where s.rubric_version = (select version from bareme)
          and s.valeur is not null
          -- La contre-note manuelle sert à contrôler le juge, pas à le
          -- remplacer : même règle qu'à l'affichage (`catalog.py`).
          and s.modele not like 'claude%%'
          and s.oeuvre_id in (select id from oeuvres)
        order by s.oeuvre_id, s.axe, (s.modele = 'interne-ridge'), s.scored_at desc
    ),
    -- `having` : un vecteur incomplet n'est pas un vecteur. Une œuvre notée
    -- sur cinq axes sur six n'entre pas dans le graphe avec un trou — elle y
    -- entre sans empreinte, ce qui est une information juste, là où un zéro ou
    -- une moyenne bouchée serait un mensonge que la distance croirait.
    vecteurs as (
        select n.oeuvre_id, n.interne,
               array_agg(n.valeur::float8 order by a.rang) as empreinte
        from notes n join axe a on a.nom = n.axe
        group by n.oeuvre_id, n.interne
        having count(*) = (select count(*) from axe)
    ),
    -- Le juge d'abord, la régression en repli — `false` trie avant `true`.
    -- C'est la règle du système : la régression ne sert que ce qui n'a pas été
    -- jugé. `empreinte_source` garde la trace sur le nœud, et ce n'est pas
    -- cosmétique : c'est ce qui permettra de mesurer séparément la dispersion
    -- des deux populations, le contrôle que réclame le §5.2 de la mission
    -- empreinte.
    empreinte as (
        select distinct on (oeuvre_id)
               oeuvre_id, empreinte,
               case when interne then 'interne' else 'juge' end as empreinte_source
        from vecteurs
        order by oeuvre_id, interne
    )
    select o.id                                     as oeuvre_id,
           o.id_tmdb,
           coalesce(v.name, o.titre)                as titre,
           v.original_name                          as titre_original,
           coalesce(extract(year from v.first_air_date)::int, o.annee) as annee,
           v.first_air_date                         as date_sortie,
           v.original_language                      as langue,
           v.status                                 as statut,
           nullif(v.poster_path, '')                as affiche,
           v.vote_count                             as votes,
           {note}                                   as note,
           -- Les genres, tels que la fiche les porte : identifiant ET libellé.
           -- Le libellé seul ferait deux nœuds pour « Science-Fiction » et
           -- « Science Fiction » le jour où TMDB retouche une chaîne.
           (select coalesce(jsonb_agg(jsonb_build_object(
                       'cle', {prefixe_genre} || (g ->> 'id'),
                       'nom', g ->> 'name')), '[]'::jsonb)
            from jsonb_array_elements(coalesce(v.genres, '[]'::jsonb)) g
            where g ->> 'id' is not null
              and nullif(btrim(g ->> 'name'), '') is not null) as genres,
           -- La distribution et les réalisateurs vivent dans le brut, pas dans
           -- la projection de vignettes. Les tableaux sont tronqués et filtrés
           -- EN SQL : une fiche de film porte des centaines de techniciens
           -- dont on retient le réalisateur.
           coalesce(
               nullif(jsonb_path_query_array(rp.payload, %(p_cast)s::jsonpath), '[]'::jsonb),
               jsonb_path_query_array(rp.payload, %(p_cast_repli)s::jsonpath)
           ) as distribution,
           jsonb_path_query_array(rp.payload, %(p_crew)s::jsonpath) as realisation,
           coalesce(rp.payload -> 'created_by', '[]'::jsonb) as creation,
           au.auteurs,
           e.empreinte,
           e.empreinte_source,
           (select version from bareme) as bareme
    from oeuvres o
    left join {vue} v on v.id = {vue_cle}
    left join empreinte e on e.oeuvre_id = o.id
    -- Les auteurs d'un livre, tels que l'enrichissement Wikidata les a
    -- canonisés ({{qid, nom}}). Null pour les autres univers — leurs facts ne
    -- portent pas la clé — et c'est le seul créditage d'un livre : pas de
    -- distribution, pas de réalisation.
    left join lateral (
        select rs.facts -> 'auteurs' as auteurs
        from riche_source rs
        where rs.oeuvre_id = o.id and rs.source = 'wikidata'
          and rs.facts ? 'auteurs'
        limit 1
    ) au on true
    left join lateral (
        select r.payload
        from raw_source r
        where r.source = %(source)s and r.kind = %(kind)s and r.source_id = o.id_tmdb::text
          and r.http_status between 200 and 299 and r.payload is not null
        order by r.fetched_at desc
        limit 1
    ) rp on true
    """
)


# --- L'indice des personnes -------------------------------------------------
#
# Un entier de 0 à 10 posé sur chaque `FivPersonne` : ce que la personne pèse
# dans le catalogue. La somme, sur ses œuvres, de la popularité de l'œuvre
# (log des votes) pondérée par la place — tête d'affiche pleine, rang du
# générique décroissant (1/(1+ordre)), réalisation presque pleine, création
# pleine — puis une échelle log calée sur la production : Leonardo DiCaprio
# vaut 10, Christopher Nolan 9, un second rôle établi 5-6, un acteur local 3,
# un figurant 0. Deux usages : pondérer la source « gens » du site public, et
# départager les homonymes — le vrai Christopher Nolan vaut 9, ses deux
# homonymes 0 et 1.
#
# À relancer après une projection : les personnes nouvelles n'ont pas
# d'indice, et `MERGE` ne recalcule rien.
INDICE_PERSONNES_CYPHER = """
MATCH (p:FivPersonne)
CALL (p) {
  MATCH (p)-[r]->(o:FivOeuvre)
  WITH CASE type(r)
         WHEN 'FIV_JOUE_DANS' THEN 1.0 / (1 + coalesce(r.ordre, 10))
         WHEN 'FIV_A_REALISE' THEN 0.9
         ELSE 1.0
       END AS poids,
       log10(1 + coalesce(o.votes, 0)) AS pop
  WITH sum(poids * pop) AS brut
  SET p.indice = toInteger(round(
      CASE WHEN brut <= 0 THEN 0
           ELSE 10.0 * log10(1 + brut) / log10(121.0) END))
} IN TRANSACTIONS OF 20000 ROWS
"""


def requete_extraction(media: Media) -> sql.Composed:
    """La requête d'extraction d'un univers, prête à exécuter."""
    # Import local : `catalog` pourrait un jour importer ce module, et le
    # cycle coûterait plus cher à démêler qu'à éviter. Même geste que dans
    # `search.requete_extraction`.
    from fiv_admin.catalog import note_ponderee

    return _EXTRACTION.format(
        vue=sql.Identifier("admin", media.card_view or "tv_card"),
        note=note_ponderee("v"),
        # Les vignettes des livres sont keyées par le pivot — pas d'id TMDB.
        vue_cle=sql.SQL("o.id") if media.pivot_card else sql.SQL("o.id_tmdb"),
        # Le préfixe de la clé de genre. Les genres d'un livre viennent de
        # Wikidata (P136), ceux des séries et des films de TMDB : deux
        # espaces de numérotation qui ne doivent jamais se rencontrer, comme
        # pour les personnes.
        prefixe_genre=sql.Literal("wd:") if media.pivot_card else sql.Literal("tmdb:"),
    )


def parametres_extraction(media: Media, ids: Sequence[int] | None = None) -> dict[str, Any]:
    """Les paramètres de l'extraction — dont les chemins jsonb, qui sont le
    seul endroit où les deux univers divergent vraiment.

    Une série consolide ses crédits sur toute sa durée (`aggregate_credits`) et
    range les métiers dans un tableau `jobs` ; un film n'a que `credits`, un
    métier par ligne. TMDB n'a jamais unifié les deux vocabulaires, et c'est
    ici qu'on le paie, une fois.
    """
    if media.univers == "series":
        p_cast = f"$.aggregate_credits.cast[0 to {DISTRIBUTION_MAX - 1}]"
        p_cast_repli = f"$.credits.cast[0 to {DISTRIBUTION_MAX - 1}]"
        p_crew = '$.aggregate_credits.crew[*] ? (@.department == "Directing")'
    else:
        p_cast = f"$.credits.cast[0 to {DISTRIBUTION_MAX - 1}]"
        p_cast_repli = p_cast
        p_crew = '$.credits.crew[*] ? (@.job == "Director")'
    return {
        "source": SOURCE,
        "kind": media.kind,
        "univers": media.univers,
        "ids": list(ids) if ids is not None else None,
        "p_cast": p_cast,
        "p_cast_repli": p_cast_repli,
        "p_crew": p_crew,
    }


# ---------------------------------------------------------------------------
# La mise en forme : une ligne d'extraction → les paramètres d'un nœud
# ---------------------------------------------------------------------------


def normaliser(vecteur: Sequence[float]) -> tuple[list[float] | None, float | None]:
    """Le vecteur ramené à la norme 1, et sa norme.

    La norme est l'intensité globale de l'œuvre — « beaucoup de tout » contre
    « un peu de tout » — que le cosinus met de côté par construction. La garder
    à part, c'est pouvoir la réintroduire comme second critère sans toucher à
    l'index.
    """
    norme = math.sqrt(sum(x * x for x in vecteur))
    if norme == 0.0:
        # Impossible avec des notes de 1 à 10, mais un vecteur nul passerait
        # sinon une division par zéro à la projection plutôt qu'ici.
        return None, None
    return [x / norme for x in vecteur], norme


def _cle(identifiant: Any) -> str | None:
    return f"tmdb:{identifiant}" if identifiant is not None else None


def _membre(membre: dict[str, Any], rang: int) -> dict[str, Any] | None:
    """Un acteur crédité. `aggregate_credits` porte les rôles dans un tableau
    `roles`, `credits` met le personnage à plat — on aplatit les deux pareil,
    comme `catalog._shape_member`."""
    cle = _cle(membre.get("id"))
    if cle is None:
        return None
    roles = membre.get("roles") or []
    personnage = membre.get("character") or (roles[0].get("character") if roles else None)
    episodes = membre.get("total_episode_count") or (
        roles[0].get("episode_count") if roles else None
    )
    return {
        "cle": cle,
        "nom": membre.get("name"),
        "photo": membre.get("profile_path"),
        "personnage": personnage or None,
        # Le rang au générique, qui est l'ordre dans lequel TMDB rend le
        # tableau. `order` existe côté film mais pas toujours côté série.
        "ordre": membre.get("order") if membre.get("order") is not None else rang,
        "episodes": episodes,
    }


def _realisateur(membre: dict[str, Any]) -> dict[str, Any] | None:
    """Un réalisateur. Côté film, le filtre jsonpath a déjà fait le tri ; côté
    série, il a laissé passer tout le département « Directing » et c'est ici
    qu'on ne garde que les réalisateurs — le tableau `jobs` n'est pas
    filtrable proprement en jsonpath."""
    cle = _cle(membre.get("id"))
    if cle is None:
        return None
    metiers = membre.get("jobs") or []
    if metiers:
        director = [m for m in metiers if m.get("job") == "Director"]
        if not director:
            return None
        episodes = membre.get("total_episode_count") or director[0].get("episode_count")
    elif membre.get("job") != "Director":
        return None
    else:
        episodes = None
    return {
        "cle": cle,
        "nom": membre.get("name"),
        "photo": membre.get("profile_path"),
        "episodes": episodes,
    }


def construire_oeuvre(row: dict[str, Any], univers: str) -> dict[str, Any]:
    """Une ligne d'extraction → le paramètre d'un lot de projection.

    Les propriétés absentes sont envoyées à `null` explicitement, jamais
    omises : `SET n += $props` retire une propriété passée à null, et c'est ce
    qui fait qu'une affiche disparue de TMDB disparaît aussi du graphe. Les
    omettre laisserait le graphe accumuler des vérités périmées.
    """
    empreinte = list(row.get("empreinte") or []) or None
    unitaire, norme = normaliser(empreinte) if empreinte else (None, None)
    date_sortie = row.get("date_sortie")
    note = row.get("note")

    distribution = [
        forme
        for rang, membre in enumerate(row.get("distribution") or [])
        if (forme := _membre(membre, rang)) is not None
    ]
    realisation = [
        forme
        for membre in row.get("realisation") or []
        if (forme := _realisateur(membre)) is not None
    ]
    # Les plus présents d'abord, puis on coupe. Un film n'atteint jamais la
    # limite ; une série de longue durée, toujours.
    realisation.sort(key=lambda m: m["episodes"] or 0, reverse=True)
    creation = [
        {"cle": cle, "nom": membre.get("name"), "photo": membre.get("profile_path")}
        for membre in row.get("creation") or []
        if (cle := _cle(membre.get("id"))) is not None
    ]
    # Les auteurs d'un livre : même relation FIV_A_CREE que les créateurs de
    # séries — « a créé » dit exactement ce qu'un auteur fait — mais une clé
    # `wd:` : la personne vient de Wikidata, pas de TMDB, et les deux espaces
    # de numérotation ne doivent jamais se rencontrer.
    creation += [
        {"cle": f"wd:{auteur['qid']}", "nom": auteur.get("nom"), "photo": None}
        for auteur in row.get("auteurs") or []
        if auteur.get("qid")
    ]

    return {
        "oeuvreId": row["oeuvre_id"],
        "props": {
            "univers": univers,
            "idTmdb": row.get("id_tmdb"),
            "titre": row.get("titre"),
            "titreOriginal": row.get("titre_original"),
            "annee": row.get("annee"),
            "dateSortie": date_sortie.isoformat() if date_sortie is not None else None,
            "langueOriginale": row.get("langue"),
            "statut": row.get("statut"),
            "affiche": row.get("affiche"),
            "note": round(float(note), 2) if note is not None else None,
            "votes": row.get("votes"),
            "empreinte": empreinte,
            "empreinteUnitaire": unitaire,
            "empreinteNorme": round(norme, 4) if norme is not None else None,
            "empreinteSource": row.get("empreinte_source"),
            # Le barème n'est porté que s'il y a une empreinte : sinon il
            # affirmerait une provenance pour un vecteur qui n'existe pas.
            "empreinteBareme": row.get("bareme") if empreinte else None,
        },
        "genres": list(row.get("genres") or []),
        "distribution": distribution,
        "realisation": realisation[:REALISATEURS_MAX],
        "creation": creation,
    }


# ---------------------------------------------------------------------------
# La projection
# ---------------------------------------------------------------------------

# Un lot, en cinq instructions. Elles pourraient tenir en une seule, et ce
# serait une erreur : `UNWIND` d'une liste vide supprime la ligne courante, si
# bien qu'une œuvre sans genre perdrait aussi sa distribution. Une instruction
# par liste, chacune repartant d'un `MATCH` sur le pivot.

_CYPHER_OEUVRES = """
UNWIND $oeuvres AS o
MERGE (n:{oeuvre} {{oeuvreId: o.oeuvreId}})
SET n:{univers}, n += o.props
WITH n
OPTIONAL MATCH (n)-[perimee]-()
WHERE type(perimee) IN $relations
DELETE perimee
"""

_CYPHER_GENRES = """
UNWIND $oeuvres AS o
MATCH (n:{oeuvre} {{oeuvreId: o.oeuvreId}})
UNWIND o.genres AS genre
MERGE (g:{genre} {{cle: genre.cle}})
SET g.nom = coalesce(genre.nom, g.nom)
MERGE (n)-[:{rel}]->(g)
"""

_CYPHER_DISTRIBUTION = """
UNWIND $oeuvres AS o
MATCH (n:{oeuvre} {{oeuvreId: o.oeuvreId}})
UNWIND o.distribution AS membre
MERGE (p:{personne} {{cle: membre.cle}})
SET p:{metier}, p.nom = coalesce(membre.nom, p.nom), p.photo = coalesce(membre.photo, p.photo)
MERGE (p)-[r:{rel}]->(n)
SET r.personnage = membre.personnage, r.ordre = membre.ordre, r.episodes = membre.episodes
"""

_CYPHER_REALISATION = """
UNWIND $oeuvres AS o
MATCH (n:{oeuvre} {{oeuvreId: o.oeuvreId}})
UNWIND o.realisation AS membre
MERGE (p:{personne} {{cle: membre.cle}})
SET p:{metier}, p.nom = coalesce(membre.nom, p.nom), p.photo = coalesce(membre.photo, p.photo)
MERGE (p)-[r:{rel}]->(n)
SET r.episodes = membre.episodes
"""

_CYPHER_CREATION = """
UNWIND $oeuvres AS o
MATCH (n:{oeuvre} {{oeuvreId: o.oeuvreId}})
UNWIND o.creation AS membre
MERGE (p:{personne} {{cle: membre.cle}})
SET p:{metier}, p.nom = coalesce(membre.nom, p.nom), p.photo = coalesce(membre.photo, p.photo)
MERGE (p)-[:{rel}]->(n)
"""


def lot_cypher(univers: str) -> tuple[str, ...]:
    """Les instructions d'un lot, pour un univers.

    Le label d'univers est écrit DANS l'instruction plutôt que passé en
    paramètre : Cypher n'accepte un label dynamique que depuis les versions
    récentes, et de toute façon `LABEL_UNIVERS` est une constante du code, pas
    une donnée. Un plan compilé par univers, c'est aussi un cache de plan qui
    ne se fait pas invalider entre deux lots.
    """
    label_univers = LABEL_UNIVERS[univers]
    return (
        _CYPHER_OEUVRES.format(oeuvre=LABEL_OEUVRE, univers=label_univers),
        _CYPHER_GENRES.format(oeuvre=LABEL_OEUVRE, genre=LABEL_GENRE, rel=REL_GENRE),
        _CYPHER_DISTRIBUTION.format(
            oeuvre=LABEL_OEUVRE, personne=LABEL_PERSONNE, metier=LABEL_ACTEUR, rel=REL_JOUE
        ),
        _CYPHER_REALISATION.format(
            oeuvre=LABEL_OEUVRE, personne=LABEL_PERSONNE, metier=LABEL_REALISATEUR, rel=REL_REALISE
        ),
        _CYPHER_CREATION.format(
            oeuvre=LABEL_OEUVRE, personne=LABEL_PERSONNE, metier=LABEL_CREATEUR, rel=REL_CREE
        ),
    )


# ---------------------------------------------------------------------------
# Les membres
# ---------------------------------------------------------------------------

# Ce que la projection lit : un membre, ses citations, rien d'autre.
#
# Trois filtres, et chacun retire du bruit plutôt que de l'information :
#
#   * `f.valide` — un top invalidé en V1 n'a pas à peser dans le voisinage ;
#   * `p.oeuvre_id is not null` — garanti par la clé étrangère, mais la
#     jointure le dit mieux que la confiance ;
#   * les membres sans aucune citation ne sortent pas : un nœud sans arête
#     n'apporte rien à une traversée et il y en aurait 8 593.
#
# Le tri par membre est ce qui permet de découper en lots sans jamais couper
# un membre en deux — chaque lot part avec des membres entiers, donc une
# reprise après incident ne laisse personne à moitié projeté.
_EXTRACTION_MEMBRES = """
select m.id                                        as membre_id,
       json_agg(json_build_object(
           'oeuvreId', p.oeuvre_id,
           'rang',     p.rang,
           'periode',  f.periode,
           'univers',  f.univers
       ) order by f.univers, f.periode, p.rang)     as citations
  from membre.membre m
  join membre.five f          on f.membre_id = m.id and f.valide
  join membre.five_position p on p.five_id = f.id
 group by m.id
 order by m.id
"""

# Deux instructions, pour la raison écrite plus haut à propos des œuvres : un
# `UNWIND` sur une liste vide supprimerait la ligne courante, et un membre dont
# toutes les citations auraient disparu perdrait aussi son nœud au lieu d'être
# simplement détaché.
_CYPHER_MEMBRES = """
UNWIND $membres AS m
MERGE (p:{membre} {{membreId: m.membreId}})
WITH p
OPTIONAL MATCH (p)-[perimee:{rel}]->()
DELETE perimee
"""

_CYPHER_CITATIONS = """
UNWIND $membres AS m
MATCH (p:{membre} {{membreId: m.membreId}})
UNWIND m.citations AS c
MATCH (o:{oeuvre} {{oeuvreId: c.oeuvreId}})
MERGE (p)-[r:{rel}]->(o)
SET r.rang = c.rang, r.periode = c.periode
"""


def lot_membres_cypher() -> tuple[str, str]:
    """Les deux instructions d'un lot de membres."""
    return (
        _CYPHER_MEMBRES.format(membre=LABEL_MEMBRE, rel=REL_CITE),
        _CYPHER_CITATIONS.format(membre=LABEL_MEMBRE, oeuvre=LABEL_OEUVRE, rel=REL_CITE),
    )


# `CREATE CONSTRAINT nom`, `CREATE INDEX nom`, `CREATE VECTOR INDEX nom` — le
# nom ne tombe pas au même rang selon le type, d'où la lecture par motif.
_NOM_SCHEMA = re.compile(r"^CREATE (?:CONSTRAINT|(?:\w+ )?INDEX) (\w+)")


async def poser_schema(graphe: Graphe, dimensions: int) -> list[str]:
    """Contraintes et index. Idempotent, et à rejouer après tout changement de
    barème — c'est là que la dimension des index se vérifie."""
    posees: list[str] = []
    for instruction in schema_cypher(dimensions):
        await graphe.executer(instruction)
        trouve = _NOM_SCHEMA.match(instruction)
        posees.append(trouve.group(1) if trouve else instruction[:40])
    return posees


# Ce qui a bougé depuis le marqueur, en pivots.
#
# Trois portes d'entrée, et la troisième est celle qu'un index de recherche n'a
# pas : une œuvre peut changer dans le graphe **sans que rien n'ait été
# collecté**, parce qu'elle vient d'être notée. Une campagne `training note` ne
# touche ni `raw_source` ni `fetch_state` — elle écrit dans `notation.score` —
# et sans cette troisième porte les empreintes fraîches n'entreraient jamais.
_PIVOTS_CHANGES = """
    select distinct o.id
    from oeuvre o
    where o.univers = %(univers)s
      and (
        -- l'œuvre est neuve (la collecte crée son pivot)
        o.created_at > %(depuis)s::timestamptz
        -- sa fiche a été recollectée : titre, genres ou distribution ont pu bouger
        or exists (
            select 1 from fetch_state s
            where s.source = %(source)s and s.kind = %(kind)s
              and s.source_id = o.id_tmdb::text
              and s.last_fetched_at > %(depuis)s::timestamptz)
        -- elle a été notée, ou renotée, ou estimée par la régression
        or exists (
            select 1 from notation.score sc
            where sc.oeuvre_id = o.id and sc.scored_at > %(depuis)s::timestamptz)
        -- son enrichissement a bougé — la porte des livres, dont toute la
        -- matière (auteurs compris) vit dans riche_source, et que ni
        -- fetch_state (source_id = QID) ni tmdb_catalog ne voient
        or exists (
            select 1 from riche_source rs
            where rs.oeuvre_id = o.id and rs.fetched_at > %(depuis)s::timestamptz)
      )
"""


async def _horloge_base(conn: psycopg.AsyncConnection) -> str:
    """L'heure de la BASE, en ISO. C'est contre elle que `fetch_state` et
    `notation.score` sont horodatés — celle du poste peut en diverger."""
    async with conn.cursor() as cur:
        await cur.execute("select now()")
        row = await cur.fetchone()
    return row[0].isoformat()


async def lire_marqueur(graphe: Graphe, univers: str) -> str | None:
    lignes = await graphe.executer(
        f"MATCH (e:{LABEL_ETAT} {{univers: $univers}}) RETURN e.synchroniseLe AS marqueur",
        univers=univers,
    )
    return lignes[0]["marqueur"] if lignes else None


async def poser_marqueur(graphe: Graphe, univers: str, horodatage: str) -> None:
    await graphe.executer(
        f"MERGE (e:{LABEL_ETAT} {{univers: $univers}}) SET e.synchroniseLe = $horodatage",
        univers=univers,
        horodatage=horodatage,
    )


async def _projeter_pivots(
    conn: psycopg.AsyncConnection,
    graphe: Graphe,
    media: Media,
    *,
    lot: int,
    ids: Sequence[int] | None,
    avancement: Callable[[int], None] | None,
) -> int:
    """Extrait (tout l'univers, ou les seuls pivots) et envoie par lots."""
    instructions = lot_cypher(media.univers)
    relations = list(RELATIONS_PROJETEES)
    total = 0

    async def envoyer(paquet: list[dict[str, Any]]) -> None:
        for instruction in instructions:
            await graphe.executer(instruction, oeuvres=paquet, relations=relations)

    # Curseur serveur : l'univers entier ne tient pas en mémoire, et le bloc de
    # transaction évite qu'un `with hold` matérialise le résultat.
    async with (
        conn.transaction(),
        conn.cursor(name="graphe_extraction", row_factory=dict_row) as cur,
    ):
        cur.itersize = lot
        await cur.execute(requete_extraction(media), parametres_extraction(media, ids))
        paquet: list[dict[str, Any]] = []
        async for row in cur:
            paquet.append(construire_oeuvre(row, media.univers))
            if len(paquet) >= lot:
                await envoyer(paquet)
                total += len(paquet)
                paquet = []
                if avancement is not None:
                    avancement(total)
        if paquet:
            await envoyer(paquet)
            total += len(paquet)
    return total


async def synchroniser(
    conn: psycopg.AsyncConnection,
    graphe: Graphe,
    media: Media,
    *,
    lot: int = 500,
) -> dict[str, Any]:
    """Rattrape le graphe vivant : ce qui a bougé depuis le marqueur.

    C'est la voie du quotidien, celle que la passe nocturne enchaîne après
    `catalog refresh` — collecte du jour et notes fraîches entrent dans le
    graphe sans le reconstruire. Quelques secondes pour une passe ordinaire,
    contre une projection complète qui relit tout l'univers.

    Ce qu'elle ne fait pas, et il faut le savoir : retirer une œuvre disparue
    du catalogue, et purger un genre ou une personne devenus orphelins. La
    projection complète non plus, d'ailleurs — voir `elaguer`. Sans marqueur,
    elle refuse plutôt que de deviner : un graphe sans point de reprise ne peut
    pas dire ce qui lui manque.
    """
    depuis = await lire_marqueur(graphe, media.univers)
    if not depuis:
        return {
            "univers": media.univers,
            "erreur": "pas de marqueur — lancer `graphe projeter` une première fois",
        }

    # L'heure AVANT la lecture des pivots : ce qui bouge pendant l'envoi sera
    # revu au prochain passage — un recouvrement, jamais un trou.
    maintenant = await _horloge_base(conn)
    async with conn.cursor() as cur:
        await cur.execute(
            _PIVOTS_CHANGES,
            {
                "source": SOURCE,
                "kind": media.kind,
                "univers": media.univers,
                "depuis": depuis,
            },
        )
        pivots = [row[0] for row in await cur.fetchall()]

    total = 0
    if pivots:
        total = await _projeter_pivots(conn, graphe, media, lot=lot, ids=pivots, avancement=None)
    await poser_marqueur(graphe, media.univers, maintenant)
    return {"univers": media.univers, "changees": len(pivots), "oeuvres": total}


async def projeter(
    conn: psycopg.AsyncConnection,
    graphe: Graphe,
    media: Media,
    *,
    lot: int = 500,
    ids: Sequence[int] | None = None,
    avancement: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Postgres → Neo4j, un univers, par lots.

    Idempotent par construction : `MERGE` sur le pivot, et les relations que la
    projection possède sont effacées puis réécrites œuvre par œuvre. Relancer
    la commande deux fois de suite donne exactement le même graphe — et un
    genre retiré d'une fiche recollectée disparaît, ce qu'un `MERGE` seul ne
    saurait pas faire.

    Le régime est celui de `search reindex` : on projette un état, jamais un
    delta. Restreindre la liste des pivots limite le travail, pas le résultat.

    Limite connue, assumée pour l'instant : les cinq instructions d'un lot
    partent en cinq requêtes, donc en cinq transactions. Entre l'effacement des
    relations et leur réécriture, une œuvre est momentanément nue. C'est sans
    conséquence tant que le graphe se construit — personne ne le lit — et ça
    cessera de l'être le jour où il sert des recommandations. Le remède est
    connu et local : les transactions explicites de la Query API
    (`/db/<base>/query/v2/tx`), qui permettent d'ouvrir, d'enchaîner les cinq
    instructions et de valider d'un bloc.
    """
    # L'heure de départ, AVANT l'extraction : tout ce qui bouge pendant la
    # projection sera revu par la première synchronisation — un recouvrement
    # plutôt qu'un trou.
    depart = await _horloge_base(conn)
    total = await _projeter_pivots(conn, graphe, media, lot=lot, ids=ids, avancement=avancement)
    # Le marqueur n'est posé que par une projection COMPLÈTE : après une
    # projection partielle il affirmerait que tout est à jour à cette heure, ce
    # qui creuserait un trou pour toutes les œuvres non listées.
    if ids is None:
        await poser_marqueur(graphe, media.univers, depart)
    return {"univers": media.univers, "oeuvres": total}


async def projeter_membres(
    conn: psycopg.AsyncConnection,
    graphe: Graphe,
    *,
    lot: int = 500,
    avancement: Callable[[int], None] | None = None,
) -> dict[str, int]:
    """Les membres et leurs citations, en nœuds anonymes.

    C'est le second versant du graphe : le premier décrit les œuvres, celui-ci
    dit qui cite quoi. Ensemble ils ouvrent la traversée qui fait la
    recommandation communautaire —

        (moi)-[:FIV_CITE]->(oeuvre)<-[:FIV_CITE]-(voisin)-[:FIV_CITE]->(reco)

    — où le voisin est quelqu'un dont on ne sait rien, sinon qu'il a aimé les
    mêmes choses. C'est suffisant, et c'est tout ce qu'on veut savoir.

    **Une œuvre absente du graphe est ignorée en silence**, par construction :
    la seconde instruction fait `MATCH` sur le pivot, pas `MERGE`. Une citation
    vers une œuvre jamais projetée ne crée donc pas un nœud vide qui
    ressemblerait à une œuvre — elle attend simplement que `graphe projeter`
    passe. Le compte rendu dit combien de citations sont ainsi restées à quai.

    Idempotent comme la projection des œuvres : `MERGE` sur le membre, les
    `FIV_CITE` du membre effacées puis réécrites. Un top raccourci depuis la
    dernière passe perd bien ses positions en trop.
    """
    instructions = lot_membres_cypher()
    membres = 0
    citations = 0

    async def envoyer(paquet: list[dict[str, Any]]) -> None:
        for instruction in instructions:
            await graphe.executer(instruction, membres=paquet)

    async with (
        conn.transaction(),
        conn.cursor(name="graphe_membres", row_factory=dict_row) as cur,
    ):
        cur.itersize = lot
        await cur.execute(_EXTRACTION_MEMBRES)
        paquet: list[dict[str, Any]] = []
        async for row in cur:
            paquet.append({"membreId": row["membre_id"], "citations": row["citations"]})
            citations += len(row["citations"])
            if len(paquet) >= lot:
                await envoyer(paquet)
                membres += len(paquet)
                paquet = []
                if avancement is not None:
                    avancement(membres)
        if paquet:
            await envoyer(paquet)
            membres += len(paquet)

    # Ce que le graphe a réellement retenu, relu chez lui plutôt que déduit de
    # ce qu'on a envoyé : l'écart, ce sont les citations dont l'œuvre n'est pas
    # projetée, et c'est précisément le chiffre qu'on veut voir.
    posees = await graphe.executer(
        une_ligne(f"MATCH (:{LABEL_MEMBRE})-[r:{REL_CITE}]->() RETURN count(r) AS n")
    )
    retenues = int(posees[0]["n"]) if posees else 0
    return {
        "membres": membres,
        "citations": citations,
        "citationsPosees": retenues,
        "citationsSansOeuvre": max(0, citations - retenues),
    }


async def elaguer(graphe: Graphe, *, lot: int = 10_000) -> dict[str, int]:
    """Supprime les genres et les personnes que plus aucune œuvre ne cite.

    Ni la projection ni la synchronisation ne le font, et c'est volontaire :
    elles raisonnent œuvre par œuvre, et une personne détachée d'un film reste
    peut-être au générique de vingt autres. Savoir qu'elle est devenue
    orpheline demande de regarder le graphe entier — c'est un balayage, pas un
    effet de bord.

    Le cas se produit quand une fiche recollectée perd un acteur, ou qu'un
    genre disparaît du référentiel TMDB. C'est rare, ça ne fausse rien (un nœud
    sans relation ne remonte dans aucune traversée), mais ça encombre les
    comptes de `graphe etat`.

    Par tranches : Neo4j garde en mémoire tout ce qu'une transaction supprime,
    et un `DELETE` sur des centaines de milliers de nœuds d'un seul tenant est
    la façon classique de faire tomber la JVM sur un dépassement de tas.
    """
    supprimes: dict[str, int] = {}

    # D'abord les labels de métier devenus faux. Une personne qui perd son
    # dernier rôle d'acteur reste une personne — elle a peut-être réalisé — mais
    # elle n'est plus `:FivActeur`. Sans ce passage, les labels s'accumulent et
    # `MATCH (a:FivActeur)` finit par rendre des gens qui ne jouent nulle part.
    for relation, label in LABEL_DU_ROLE.items():
        total = 0
        while True:
            lignes = await graphe.executer(
                f"MATCH (p:{label}) WHERE NOT (p)-[:{relation}]->()"
                f" WITH p LIMIT $lot REMOVE p:{label} RETURN count(p) AS n",
                lot=lot,
            )
            retire = lignes[0]["n"] if lignes else 0
            total += retire
            if retire < lot:
                break
        if total:
            supprimes[f"{label} (label retire)"] = total

    for label in (LABEL_PERSONNE, LABEL_GENRE):
        total = 0
        while True:
            lignes = await graphe.executer(
                f"MATCH (n:{label}) WHERE NOT (n)--() WITH n LIMIT $lot"
                f" DETACH DELETE n RETURN count(n) AS n",
                lot=lot,
            )
            efface = lignes[0]["n"] if lignes else 0
            total += efface
            if efface < lot:
                break
        supprimes[label] = total
    return supprimes


async def etat(graphe: Graphe) -> dict[str, Any]:
    """Ce que le graphe contient, et si ses index sont en ligne.

    Le compte des empreintes est séparé du compte des œuvres, et par source :
    c'est le seul chiffre qui dit si la recommandation a de quoi travailler.
    Un graphe complet en nœuds mais vide en vecteurs répond à « qui joue
    dedans » et à rien d'autre.
    """
    marqueurs = {
        ligne["univers"]: ligne["marqueur"]
        for ligne in await graphe.executer(
            f"MATCH (e:{LABEL_ETAT}) RETURN e.univers AS univers, e.synchroniseLe AS marqueur"
        )
    }
    noeuds = await graphe.executer(
        f"MATCH (o:{LABEL_OEUVRE}) RETURN o.univers AS univers, count(*) AS oeuvres,"
        f" count(o.empreinte) AS empreintes,"
        f" sum(CASE WHEN o.empreinteSource = 'juge' THEN 1 ELSE 0 END) AS jugees"
        f" ORDER BY univers"
    )
    genres = await graphe.executer(f"MATCH (g:{LABEL_GENRE}) RETURN count(*) AS n")
    personnes = await graphe.executer(f"MATCH (p:{LABEL_PERSONNE}) RETURN count(*) AS n")
    # Par métier, et la somme dépasse le total : une personne qui joue et
    # réalise est comptée deux fois, parce qu'elle porte les deux labels. C'est
    # le signe que le modèle tient — deux nœuds, ce serait la même personne
    # dédoublée.
    metiers = {
        label: (await graphe.executer(f"MATCH (p:{label}) RETURN count(*) AS n"))[0]["n"]
        for label in (LABEL_ACTEUR, LABEL_REALISATEUR, LABEL_CREATEUR)
    }
    relations = await graphe.executer(
        "MATCH ()-[r]->() WHERE type(r) IN $relations"
        " RETURN type(r) AS type, count(*) AS n ORDER BY type",
        relations=list(RELATIONS_PROJETEES),
    )
    index = await graphe.executer(
        "SHOW INDEXES YIELD name, type, state"
        f" WHERE name STARTS WITH '{PREFIXE.lower()}'"
        " RETURN name, type, state ORDER BY name"
    )
    for ligne in noeuds:
        ligne["marqueur"] = marqueurs.get(ligne["univers"])
    return {
        "univers": noeuds,
        "genres": genres[0]["n"] if genres else 0,
        "personnes": personnes[0]["n"] if personnes else 0,
        "metiers": metiers,
        "relations": relations,
        "index": index,
    }
