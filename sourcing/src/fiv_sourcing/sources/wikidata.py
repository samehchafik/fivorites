"""Wikidata : le raccordement et les faits.

Deux requêtes par série, et pas une de plus :

  1. SPARQL sur l'identifiant — c'est ce qui donne le QID, les identifiants
     externes et les faits (pays, langue, lieux).
  2. `wbgetentities` sur le QID — les sitelinks, donc le titre exact de
     l'article dans chaque Wikipédia.

**L'entrée se fait par `P4983`, l'identifiant TMDB, pas par l'`imdb_id`.** La
mesure du 2026-08-06 le justifie : entrer par IMDb suppose que TMDB nous ait
donné l'identifiant *et* que Wikidata le porte, deux conditions qui tombent
ensemble sur les catalogues arabe et turc. `P4983` n'en demande aucune — il se
déduit de l'id qu'on a déjà. `P345` reste en second recours parce qu'il couvre
mieux le catalogue occidental.

Aucun jeton, aucun quota : c'est ce qui permet à l'enrichissement de tourner
même quand la collecte TMDB est bloquée.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from fiv_sourcing.http import FetchResult, HttpFetcher

log = logging.getLogger(__name__)

SOURCE = "wikidata"
SPARQL_URL = "https://query.wikidata.org/sparql"
ENTITY_URL = "https://www.wikidata.org/w/api.php"

# Un seul motif, paramétré par la propriété d'entrée. Les faits demandés sont
# ceux dont la couche 1 aura besoin — pays et langue pour la taxonomie
# « origine », P915/P840 pour la couche géographique.
LOOKUP = """
SELECT ?item ?imdb ?tvmaze
       (GROUP_CONCAT(DISTINCT ?paysCode; separator="|") AS ?pays)
       (GROUP_CONCAT(DISTINCT ?langueCode; separator="|") AS ?langues)
       (GROUP_CONCAT(DISTINCT ?tournageNom; separator="|") AS ?tournage)
       (GROUP_CONCAT(DISTINCT ?actionNom; separator="|") AS ?action)
WHERE {
  ?item wdt:%(propriete)s "%(valeur)s" .
  OPTIONAL { ?item wdt:P345 ?imdb }
  OPTIONAL { ?item wdt:P8600 ?tvmaze }
  OPTIONAL { ?item wdt:P495 ?paysItem . ?paysItem wdt:P297 ?paysCode }
  OPTIONAL { ?item wdt:P364 ?langueItem . ?langueItem wdt:P218 ?langueCode }
  OPTIONAL { ?item wdt:P915 ?tournageItem . ?tournageItem rdfs:label ?tournageNom .
             FILTER(lang(?tournageNom) = "en") }
  OPTIONAL { ?item wdt:P840 ?actionItem . ?actionItem rdfs:label ?actionNom .
             FILTER(lang(?actionNom) = "en") }
}
GROUP BY ?item ?imdb ?tvmaze
LIMIT 1
"""


# La même chose pour cent séries d'un coup. `VALUES` fait tout le travail.
#
# Sans ce lot, enrichir le catalogue entier voudrait dire 228 000 requêtes
# SPARQL contre un service gratuit et partagé — ce qui, indépendamment du temps
# que ça prendrait, ne se fait pas. Par cent, c'est 2 300 requêtes.
LOOKUP_LOT = """
SELECT ?tmdb ?item ?imdb ?tvmaze
       (GROUP_CONCAT(DISTINCT ?paysCode; separator="|") AS ?pays)
       (GROUP_CONCAT(DISTINCT ?langueCode; separator="|") AS ?langues)
       (GROUP_CONCAT(DISTINCT ?tournageNom; separator="|") AS ?tournage)
       (GROUP_CONCAT(DISTINCT ?actionNom; separator="|") AS ?action)
WHERE {
  VALUES ?tmdb { %(valeurs)s }
  ?item wdt:P4983 ?tmdb .
  OPTIONAL { ?item wdt:P345 ?imdb }
  OPTIONAL { ?item wdt:P8600 ?tvmaze }
  OPTIONAL { ?item wdt:P495 ?paysItem . ?paysItem wdt:P297 ?paysCode }
  OPTIONAL { ?item wdt:P364 ?langueItem . ?langueItem wdt:P218 ?langueCode }
  OPTIONAL { ?item wdt:P915 ?tournageItem . ?tournageItem rdfs:label ?tournageNom .
             FILTER(lang(?tournageNom) = "en") }
  OPTIONAL { ?item wdt:P840 ?actionItem . ?actionItem rdfs:label ?actionNom .
             FILTER(lang(?actionNom) = "en") }
}
GROUP BY ?tmdb ?item ?imdb ?tvmaze
"""


class WikidataClient:
    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def by_tmdb(self, tv_id: int) -> FetchResult:
        return await self._sparql("P4983", str(tv_id))

    async def by_tmdb_lot(self, ids: Sequence[int]) -> FetchResult:
        """Résout jusqu'à quelques centaines d'ids en une requête."""
        valeurs = " ".join(f'"{int(i)}"' for i in ids)
        return await self._fetcher.get_json(
            SPARQL_URL, {"query": LOOKUP_LOT % {"valeurs": valeurs}, "format": "json"}
        )

    async def by_imdb(self, imdb_id: str) -> FetchResult:
        return await self._sparql("P345", imdb_id)

    async def _sparql(self, propriete: str, valeur: str) -> FetchResult:
        # `valeur` vient d'un id TMDB (entier) ou d'un imdb_id validé en amont ;
        # le guillemet est malgré tout échappé, parce qu'une injection SPARQL
        # sur une chaîne non contrôlée serait silencieuse.
        requete = LOOKUP % {"propriete": propriete, "valeur": valeur.replace('"', '\\"')}
        return await self._fetcher.get_json(SPARQL_URL, {"query": requete, "format": "json"})

    async def entity(self, qid: str) -> FetchResult:
        """Sitelinks et libellés. `props` restreint : l'entité complète d'une
        série connue pèse plusieurs centaines de kilooctets pour deux champs."""
        return await self._fetcher.get_json(
            ENTITY_URL,
            {
                "action": "wbgetentities",
                "ids": qid,
                "props": "sitelinks|labels",
                "format": "json",
            },
        )


def _aplatir(ligne: dict[str, Any]) -> dict[str, Any] | None:
    def champ(nom: str) -> str:
        return ligne.get(nom, {}).get("value", "")

    def liste(nom: str) -> list[str]:
        return [x for x in champ(nom).split("|") if x]

    qid = champ("item").rsplit("/", 1)[-1]
    if not qid:
        return None
    return {
        "qid": qid,
        "imdb": champ("imdb") or None,
        "tvmaze": champ("tvmaze") or None,
        "pays": liste("pays"),
        "langues": liste("langues"),
        "lieux_tournage": liste("tournage"),
        "lieux_action": liste("action"),
    }


def lire_lookup(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Aplatit la réponse SPARQL. None si l'item n'existe pas."""
    lignes = ((payload or {}).get("results") or {}).get("bindings") or []
    return _aplatir(lignes[0]) if lignes else None


def lire_lookup_lot(payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """{id TMDB: faits}. Les ids absents de la réponse n'ont pas d'item —
    c'est le cas majoritaire, et ce n'est pas une erreur."""
    trouves: dict[int, dict[str, Any]] = {}
    for ligne in ((payload or {}).get("results") or {}).get("bindings") or []:
        brut = ligne.get("tmdb", {}).get("value", "")
        faits = _aplatir(ligne)
        if faits and brut.isdigit():
            trouves[int(brut)] = faits
    return trouves


# Les champs agrégés par GROUP_CONCAT dans les deux requêtes de lookup.
_CHAMPS_GROUPES = ("pays", "langues", "tournage", "action")


def canonicaliser(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Trie les valeurs des `GROUP_CONCAT`, en place.

    Blazegraph ne garantit pas leur ordre : deux réponses au même contenu
    peuvent différer par la seule permutation de « Malta|Croatia|Morocco » —
    constaté en vrai, une ligne de brut en plus à chaque rejeu. L'ordre n'est
    pas une information ; le trier avant stockage est le même geste que les
    clés JSON triées de l'empreinte, pas une interprétation du brut. Bonus :
    les `facts` dérivés deviennent stables d'une passe à l'autre.
    """
    for ligne in ((payload or {}).get("results") or {}).get("bindings") or []:
        for champ in _CHAMPS_GROUPES:
            noeud = ligne.get(champ)
            if noeud and noeud.get("value"):
                noeud["value"] = "|".join(sorted(noeud["value"].split("|")))
    return payload


def enveloppe(ligne_brute: dict[str, Any]) -> dict[str, Any]:
    """Réemballe une ligne d'un lot au format d'une réponse à une seule série.

    Le lot est une optimisation de transport ; l'unité qu'on **conserve** reste
    l'objet (R2). Sans ce réemballage, `raw_source` porterait une ligne couvrant
    cent séries, dont ni l'empreinte, ni la fraîcheur, ni le statut ne
    voudraient plus rien dire pour aucune d'elles.
    """
    return {"results": {"bindings": [ligne_brute]}}


def lignes_par_id(payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """{id TMDB: sa ligne brute}, pour en garder le détail par série."""
    par_id = {}
    for ligne in ((payload or {}).get("results") or {}).get("bindings") or []:
        brut = ligne.get("tmdb", {}).get("value", "")
        if brut.isdigit():
            par_id[int(brut)] = ligne
    return par_id


def lire_sitelinks(payload: dict[str, Any] | None, qid: str) -> dict[str, str]:
    """{code langue: titre de l'article}, pour les Wikipédias seulement.

    Wikidata mélange dans `sitelinks` les wikis de toutes natures — wikiquote,
    wikisource, commons. On ne garde que les `*wiki`, qui sont les Wikipédias.
    """
    entite = ((payload or {}).get("entities") or {}).get(qid) or {}
    articles = {}
    for cle, lien in (entite.get("sitelinks") or {}).items():
        if cle.endswith("wiki") and not cle.startswith("commons"):
            articles[cle[: -len("wiki")]] = lien.get("title", "")
    return {k: v for k, v in articles.items() if v}
