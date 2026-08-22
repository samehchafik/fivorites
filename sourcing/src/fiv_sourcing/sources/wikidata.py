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
  ?item wdt:%(propriete)s ?tmdb .
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


# Le lookup d'un item déjà identifié — le flux 2 entre par le QID, pas par un
# identifiant externe. Même SELECT que LOOKUP : mêmes faits, même parsing.
LOOKUP_QID = """
SELECT ?item ?imdb ?tvmaze
       (GROUP_CONCAT(DISTINCT ?paysCode; separator="|") AS ?pays)
       (GROUP_CONCAT(DISTINCT ?langueCode; separator="|") AS ?langues)
       (GROUP_CONCAT(DISTINCT ?tournageNom; separator="|") AS ?tournage)
       (GROUP_CONCAT(DISTINCT ?actionNom; separator="|") AS ?action)
WHERE {
  BIND(wd:%(qid)s AS ?item)
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
"""


# Le balayage du flux 2 : les items « série télévisée » sans identifiant TMDB.
#
# `ORDER BY ?item` n'est pas cosmétique : sans ordre stable, la pagination par
# OFFSET peut sauter ou répéter des items d'une page à l'autre.
#
# `%(filtres)s` reçoit le filtre de langue (P364 → P218) et, par défaut,
# l'exclusion des items à imdb_id — ceux-là sont très probablement des séries
# présentes dans TMDB mais non reliées, que le flux 1 rattrape déjà par P345.
# Les crawler créerait des doublons en masse ; la cible est le noyau dur,
# injoignable par tout autre chemin (mesuré : 300 des 480 séries de langue
# arabe).
SWEEP = """
SELECT ?item ?itemLabel ?imdb ?tvmaze WHERE {
  ?item wdt:P31 wd:Q5398426 .
  FILTER NOT EXISTS { ?item wdt:P4983 [] }
  OPTIONAL { ?item wdt:P345 ?imdb }
  OPTIONAL { ?item wdt:P8600 ?tvmaze }
  %(filtres)s
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ar,tr,fr,es". }
}
ORDER BY ?item
LIMIT %(limite)d
OFFSET %(decalage)d
"""


# Le balayage des livres.
#
# **`ORDER BY ?item`, et le tri par notoriété se fait chez nous.** La version
# triée par `DESC(?sitelinks)` côté serveur paraissait plus naturelle — elle
# fait entrer d'abord les œuvres qu'un membre a une chance de citer — mais
# elle étrangle WDQS : mesuré le 2026-08-21, le corpus anglais rend 504 après
# 65 s, et même en bandes de notoriété (« 30 à 60 sitelinks ») une requête sur
# deux échoue. Ce n'est pas le volume qui coûte — les corpus filtrés sont
# petits (fr 1 193, es 325, ar 220 œuvres à 5 sitelinks et plus) — c'est le
# **tri global** sur un ensemble que le moteur doit d'abord matérialiser.
#
# `ORDER BY ?item` est l'ordre du crawler des séries, éprouvé sur 44 700
# items : la pagination par OFFSET y est stable et chaque page se sert par
# index. `sweep()` récupère toutes les pages, puis classe par notoriété
# décroissante avant de rendre — le résultat est le même, sans la fragilité.
#
# La sous-requête reste : jointe aux OPTIONAL et au service d'étiquettes, la
# version à plat dépasse le délai même ainsi.
#
# `sitelinks_min` borne le périmètre — en dessous, l'item est un article
# unique dans une seule langue, sans matière à notation. `?olid` (P648) est
# l'identifiant Open Library : présent, il évite la recherche par titre à
# l'enrichissement (93 % des grandes œuvres françaises le portent, 23 % des
# arabes).
SWEEP_LIVRES = """
SELECT ?item ?itemLabel ?olid ?sitelinks WHERE {
  { SELECT DISTINCT ?item ?sitelinks WHERE {
      VALUES ?classe { %(classes)s }
      ?item wdt:P31 ?classe ; wikibase:sitelinks ?sitelinks .
      %(filtres)s
      FILTER(?sitelinks >= %(sitelinks_min)d)
    } ORDER BY ?item LIMIT %(limite)d OFFSET %(decalage)d }
  OPTIONAL { ?item wdt:P648 ?olid }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,es,ar". }
}
ORDER BY ?item
"""


# Le lookup d'un livre par QID — le pendant de LOOKUP_QID, avec les faits d'un
# livre : l'OLID (P648), les auteurs (P50), la langue d'origine (P407, là où
# une série porte P364), le pays (P495) et l'année de publication (P577).
#
# Les auteurs sont concaténés en paires `QID~libellé` : deux GROUP_CONCAT
# séparés ne se recolleraient pas (Blazegraph ne garantit pas leurs ordres
# respectifs), et le graphe a besoin des deux — le QID comme clé de personne,
# le libellé pour l'affichage. Libellé anglais d'abord, arabe en repli : les
# auteurs arabes sans libellé anglais existent, l'inverse est rare.
LOOKUP_QID_LIVRE = """
SELECT ?item ?olid ?sitelinks
       (GROUP_CONCAT(DISTINCT ?auteurPaire; separator="|") AS ?auteurs)
       (GROUP_CONCAT(DISTINCT ?langueCode; separator="|") AS ?langues)
       (GROUP_CONCAT(DISTINCT ?paysCode; separator="|") AS ?pays)
       (MIN(?anneePub) AS ?annee)
WHERE {
  BIND(wd:%(qid)s AS ?item)
  # Le nombre de Wikipédias qui consacrent un article à l'œuvre. C'est le
  # proxy de notoriété de l'univers livre — celui par lequel le balayage
  # classe déjà — et il est gratuit ici : un attribut de l'item, pas une
  # jointure. Voir `normalize.CLES` pour ce qu'il devient.
  OPTIONAL { ?item wikibase:sitelinks ?sitelinks }
  OPTIONAL { ?item wdt:P648 ?olid }
  OPTIONAL {
    ?item wdt:P50 ?auteur .
    OPTIONAL { ?auteur rdfs:label ?lEn . FILTER(lang(?lEn) = "en") }
    OPTIONAL { ?auteur rdfs:label ?lAr . FILTER(lang(?lAr) = "ar") }
    BIND(CONCAT(STRAFTER(STR(?auteur), "/entity/"), "~", COALESCE(?lEn, ?lAr, ""))
         AS ?auteurPaire)
  }
  OPTIONAL { ?item wdt:P407 ?langueItem . ?langueItem wdt:P218 ?langueCode }
  OPTIONAL { ?item wdt:P495 ?paysItem . ?paysItem wdt:P297 ?paysCode }
  OPTIONAL { ?item wdt:P577 ?datePub . BIND(YEAR(?datePub) AS ?anneePub) }
}
GROUP BY ?item ?olid ?sitelinks
"""


class WikidataClient:
    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def by_tmdb(self, tv_id: int, *, propriete: str = "P4983") -> FetchResult:
        """`P4983` pour une série, `P4947` pour un film.

        Wikidata sépare les deux parce que les deux catalogues TMDB se
        numérotent indépendamment. Entrer par la mauvaise propriété ne lève
        aucune erreur : elle ramène l'œuvre qui porte le même numéro dans
        l'autre catalogue.
        """
        return await self._sparql(propriete, str(tv_id))

    async def by_qid(self, qid: str) -> FetchResult:
        """Les faits d'un item déjà identifié — l'entrée du flux 2."""
        propre = "".join(c for c in qid if c.isalnum())
        return await self._fetcher.get_json(
            SPARQL_URL, {"query": LOOKUP_QID % {"qid": propre}, "format": "json"}
        )

    async def by_qid_livre(self, qid: str) -> FetchResult:
        """Les faits d'un livre déjà identifié — l'entrée du crawler livres."""
        propre = "".join(c for c in qid if c.isalnum())
        return await self._fetcher.get_json(
            SPARQL_URL, {"query": LOOKUP_QID_LIVRE % {"qid": propre}, "format": "json"}
        )

    async def sweep_livres(
        self,
        *,
        classes: Sequence[str],
        langue: str | None = None,
        sitelinks_min: int = 5,
        limite: int = 2000,
        decalage: int = 0,
    ) -> FetchResult:
        """Une page du balayage des œuvres littéraires, par identifiant.

        L'ordre est celui du crawler des séries, et le classement par
        notoriété se fait dans `sweep()` — voir `SWEEP_LIVRES` pour la mesure
        qui a tranché.
        """
        filtres = []
        if langue:
            propre = "".join(c for c in langue if c.isalpha())[:3]
            filtres.append(f'?item wdt:P407 ?langueF . ?langueF wdt:P218 "{propre}" .')
        requete = SWEEP_LIVRES % {
            "classes": " ".join(f"wd:{c}" for c in classes),
            "filtres": "\n      ".join(filtres),
            "sitelinks_min": int(sitelinks_min),
            "limite": limite,
            "decalage": decalage,
        }
        return await self._fetcher.get_json(SPARQL_URL, {"query": requete, "format": "json"})

    async def sweep_sans_tmdb(
        self,
        *,
        langue: str | None = None,
        avec_imdb: bool = False,
        limite: int = 2000,
        decalage: int = 0,
    ) -> FetchResult:
        """Une page du balayage des items série sans identifiant TMDB."""
        filtres = []
        if not avec_imdb:
            filtres.append("FILTER NOT EXISTS { ?item wdt:P345 [] }")
        if langue:
            propre = "".join(c for c in langue if c.isalpha())[:3]
            filtres.append(f'?item wdt:P364 ?langueF . ?langueF wdt:P218 "{propre}" .')
        requete = SWEEP % {
            "filtres": "\n  ".join(filtres),
            "limite": limite,
            "decalage": decalage,
        }
        return await self._fetcher.get_json(SPARQL_URL, {"query": requete, "format": "json"})

    async def by_tmdb_lot(self, ids: Sequence[int], *, propriete: str = "P4983") -> FetchResult:
        """Résout jusqu'à quelques centaines d'ids en une requête."""
        valeurs = " ".join(f'"{int(i)}"' for i in ids)
        return await self._fetcher.get_json(
            SPARQL_URL,
            {
                "query": LOOKUP_LOT % {"valeurs": valeurs, "propriete": propriete},
                "format": "json",
            },
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


# Les champs agrégés par GROUP_CONCAT dans les requêtes de lookup — séries,
# films et livres confondus : un champ absent d'une réponse est simplement
# ignoré.
_CHAMPS_GROUPES = ("pays", "langues", "tournage", "action", "auteurs")


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


def lire_sweep(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Une page de balayage → [{qid, titre, imdb, tvmaze}]."""
    items = []
    for ligne in ((payload or {}).get("results") or {}).get("bindings") or []:
        qid = ligne.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        if not qid.startswith("Q"):
            continue
        titre = ligne.get("itemLabel", {}).get("value", "")
        items.append(
            {
                "qid": qid,
                # Le service de labels renvoie le QID quand aucun libellé
                # n'existe : ce n'est pas un titre, on préfère l'absence.
                "titre": titre if titre != qid else None,
                "imdb": ligne.get("imdb", {}).get("value") or None,
                "tvmaze": ligne.get("tvmaze", {}).get("value") or None,
            }
        )
    return items


def lire_lookup_livre(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Aplatit la réponse de LOOKUP_QID_LIVRE. None si l'item n'existe pas.

    Les auteurs reviennent en paires `QID~libellé` (voir la requête) ; une
    paire au libellé vide garde son QID — la clé suffit au graphe, le nom
    viendra d'une autre passe ou pas du tout.
    """
    lignes = ((payload or {}).get("results") or {}).get("bindings") or []
    if not lignes:
        return None
    ligne = lignes[0]

    def champ(nom: str) -> str:
        return ligne.get(nom, {}).get("value", "")

    def liste(nom: str) -> list[str]:
        return [x for x in champ(nom).split("|") if x]

    qid = champ("item").rsplit("/", 1)[-1]
    if not qid:
        return None
    auteurs = []
    for paire in liste("auteurs"):
        auteur_qid, _, nom = paire.partition("~")
        if auteur_qid.startswith("Q"):
            auteurs.append({"qid": auteur_qid, "nom": nom or None})
    annee = champ("annee")
    sitelinks = champ("sitelinks")
    return {
        "qid": qid,
        "olid": champ("olid") or None,
        "sitelinks": int(sitelinks) if sitelinks.isdigit() else None,
        "auteurs": auteurs,
        "langues": liste("langues"),
        "pays": liste("pays"),
        "annee": int(annee) if annee.lstrip("-").isdigit() and int(annee) > 0 else None,
    }


def lire_sweep_livres(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Une page de balayage livres → [{qid, titre, olid, sitelinks}]."""
    items = []
    for ligne in ((payload or {}).get("results") or {}).get("bindings") or []:
        qid = ligne.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        if not qid.startswith("Q"):
            continue
        titre = ligne.get("itemLabel", {}).get("value", "")
        sitelinks = ligne.get("sitelinks", {}).get("value", "")
        items.append(
            {
                "qid": qid,
                # Même règle que le balayage des séries : le service de labels
                # renvoie le QID quand aucun libellé n'existe, et un QID n'est
                # pas un titre.
                "titre": titre if titre != qid else None,
                "olid": ligne.get("olid", {}).get("value") or None,
                "sitelinks": int(sitelinks) if sitelinks.isdigit() else 0,
            }
        )
    return items


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
