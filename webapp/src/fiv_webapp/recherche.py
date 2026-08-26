"""La recherche instantanée du composant de suggestion, servie par Elasticsearch.

Le même moteur et les mêmes index que l'admin (`fiv-admin search reindex` les
construit, la passe nocturne les rattrape) : un alias par univers, les titres
de ~45 langues aplatis dans un champ unique, les préfixes `edge_ngram` posés à
l'indexation — la frappe est un `match` sur des termes exacts, quelques
millisecondes sur 1,5 M de documents. Voir `admin/src/fiv_admin/search.py`
pour l'architecture complète ; ici, seulement la lecture.

Deux différences avec la requête de l'admin, toutes deux voulues :

* **`fiche: true` toujours** — le composant classe des œuvres qu'on peut
  montrer : une entrée d'inventaire jamais collectée n'a ni affiche ni
  synopsis, elle n'a rien à faire dans une carte de présentation ;
* **pas de pagination** — la recherche-comme-on-tape rend une seule page
  courte, reclassée à chaque frappe. Paginer une frappe n'a pas de sens :
  si le résultat n'est pas dans les premières cartes, on précise la requête.

ES reste facultatif : quand il ne répond pas, la route retombe sur l'ILIKE de
`cartes.py`, et un disjoncteur évite de payer une tentative de connexion à
chaque frappe pendant une panne.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from fiv_webapp.univers import Univers

log = logging.getLogger(__name__)

# Après un échec (connexion refusée, index absent…), ES est écarté pendant ce
# délai : la recherche retombe sur le SQL sans retenter à chaque frappe.
DISJONCTEUR_SECONDES = 30.0

# Les langues servies — les mêmes que celles indexées côté admin
# (`fiv_admin.search.LANGUES`). Chercher dans la langue de qui cherche est ce
# qui rend le résultat compréhensible : un francophone tapant « com »
# recevait des feuilletons portugais (*com* y est une préposition) affichés
# avec leur titre français, et concluait à un bug — à juste titre.
LANGUES = ("fr", "en", "es", "ar")
LANGUE_DEFAUT = "fr"


def langue_servie(demandee: str | None) -> str:
    """La langue retenue parmi celles qu'on sert. « fr-CA » donne « fr » ;
    l'inconnu retombe sur le français, langue du site."""
    racine = (demandee or "").split("-")[0].lower()
    return racine if racine in LANGUES else LANGUE_DEFAUT


def champ_titres(langue: str) -> str:
    """Le champ ES des titres d'une langue — même nom que côté admin."""
    return f"titres_{langue}"


# Le total est compté jusque-là, puis annoncé comme « au moins ». Ce qu'on en
# fait : savoir s'il reste une page à charger. Compter juste au-delà coûterait
# un balayage complet pour un chiffre que personne ne lit.
TOTAL_MAX = 500

# ES refuse `from + size` au-delà de 10 000, et il a raison : personne ne
# déroule la 400e page d'une recherche. Le composant s'arrête bien avant.
FENETRE_MAX = 10_000


@dataclass(frozen=True, slots=True)
class PageIds:
    """Ce qu'ES rend à la route : des ids classés, et de quoi savoir s'il
    reste une page."""

    ids: list[int]
    total: int
    # Le total est-il un plancher (« au moins N ») plutôt qu'un décompte ?
    tronque: bool = False
    # Le titre dans la langue demandée, par clé de vignette — vide quand
    # l'œuvre n'a pas de titre traduit dans cette langue.
    titres: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Facette:
    """Une valeur de filtre et son nombre d'œuvres — un genre, une langue."""

    valeur: str
    nombre: int

    def publique(self) -> dict[str, Any]:
        return {"valeur": self.valeur, "nombre": self.nombre}


def corps_recherche(
    texte: str,
    *,
    taille: int,
    depuis: int = 0,
    langue: str = LANGUE_DEFAUT,
    # {champ de l'index → valeurs}. Déjà résolu par l'appelant : c'est lui qui
    # sait que « plateformes » s'indexe par pays (`plateformes_fr`).
    filtres: dict[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Le corps `_search` d'une frappe du composant.

    Cinq portes d'entrée, toutes multipliées par la note bayésienne
    précalculée dans le document — jamais `popularity`, biais occidental
    mesuré. Et l'ordre des boosts porte une intention :

    * **le titre principal**, phrase exacte (×12) puis préfixes (×8). Il existe
      parce que `titres` aplatit ~45 langues : taper « com » remontait
      « Morangos com Açúcar » et le titre portugais du *Fils de Sam* — *com*
      est une préposition portugaise. Chercher dans toutes les langues reste
      juste (c'est ce qui trouve « Le Trône de fer ») ; le classement, lui,
      doit préférer le titre sous lequel l'œuvre se connaît ;
    * **les titres de la langue demandée**, phrase exacte (×6) puis préfixes
      (×4) — c'est ce qui rend la réponse lisible : on cherche dans la langue
      de qui cherche, et non dans les quarante-cinq à la fois ;
    * **tous les titres**, phrase exacte (×2) puis préfixes (×1) — la portée
      multilingue, en dernier rang : elle sert à retrouver une œuvre dont on
      ne connaît que le titre dans une langue non servie, jamais à peupler la
      liste de titres qu'on ne saurait pas lire. L'écart avec le titre
      principal est d'un
      facteur 4, et pas d'un cheveu : la note bayésienne MULTIPLIE le score,
      elle varie d'environ un facteur 2 d'une œuvre à l'autre, et un écart
      plus mince se faisait renverser par une série étrangère mieux notée —
      mesuré à 29,1 contre 28,8 avant correction ;
    * **les personnes** (×1,5) — un nom rend sa filmographie ;
    * **les genres** (×1), synonymes compris (« policier » → Crime).

    `filtres` restreint sur plusieurs dimensions à la fois — les genres, les
    plateformes. **OU à l'intérieur d'une dimension, ET entre elles** : cocher
    deux genres élargit (un ET viderait la liste dès le deuxième, la plupart
    des œuvres n'en portant que deux ou trois), tandis que cocher un genre et
    une plateforme restreint — c'est ce que « des comédies sur Netflix » veut
    dire.
    """
    filtre: list[dict[str, Any]] = [{"term": {"fiche": True}}]
    for champ, valeurs in (filtres or {}).items():
        if valeurs:
            filtre.append({"terms": {champ: list(valeurs)}})

    return {
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "match_phrase": {
                                    "titre_principal.exact": {"query": texte, "boost": 12.0}
                                }
                            },
                            {
                                "match": {
                                    "titre_principal": {
                                        "query": texte,
                                        "operator": "and",
                                        "boost": 8.0,
                                    }
                                }
                            },
                            {
                                "match_phrase": {
                                    f"{champ_titres(langue)}.exact": {
                                        "query": texte,
                                        "boost": 6.0,
                                    }
                                }
                            },
                            {
                                "match": {
                                    champ_titres(langue): {
                                        "query": texte,
                                        "operator": "and",
                                        "boost": 4.0,
                                    }
                                }
                            },
                            {"match_phrase": {"titres.exact": {"query": texte, "boost": 2.0}}},
                            {"match": {"titres": {"query": texte, "operator": "and"}}},
                            {
                                "match": {
                                    "personnes": {
                                        "query": texte,
                                        "operator": "and",
                                        "boost": 1.5,
                                    }
                                }
                            },
                            {"match": {"genres.texte": {"query": texte, "operator": "and"}}},
                        ],
                        "minimum_should_match": 1,
                        "filter": filtre,
                    }
                },
                # Une œuvre sans note vaut 5 — sous la moyenne, donc derrière
                # les œuvres notées, mais pas invisible.
                "field_value_factor": {
                    "field": "note_bayes",
                    "missing": 5.0,
                    "modifier": "none",
                },
                "boost_mode": "multiply",
            }
        },
        "from": depuis,
        "size": taille,
        # Presque rien ne voyage : les `_id`, et le titre dans la langue
        # demandée. Ce dernier n'existe QUE dans l'index — la projection
        # d'affichage ne porte qu'une langue, celle de la collecte — et le
        # demander ici évite d'aller détoaster un payload par carte.
        "_source": [champ_titres(langue)],
        # Compté, mais pas au-delà : le composant a besoin de savoir s'il
        # reste une page, pas de dénombrer 40 000 réponses. Le total exact
        # d'une frappe vague n'intéresse personne et se paie en balayage.
        "track_total_hits": TOTAL_MAX,
    }


class Recherche:
    """Le client HTTP du service, avec son disjoncteur.

    httpx plutôt qu'un client officiel — même choix que partout dans le dépôt :
    une route REST suffit. `url` vide = recherche ES désactivée, la route s'en
    tient au SQL.
    """

    def __init__(self, url: str, timeout: float = 3.0) -> None:
        self.url = (url or "").rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.url, timeout=timeout) if self.url else None
        self._coupe_jusqua = 0.0

    @property
    def active(self) -> bool:
        return self._client is not None and time.monotonic() >= self._coupe_jusqua

    async def fermer(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def documents(self, univers: Univers, cles: list[int]) -> list[dict[str, Any]] | None:
        """Les documents de plusieurs œuvres, par leur clé de vignette.

        Sert au troisième étage des suggestions : pour savoir à quoi
        ressemblent les œuvres aimées, on relit leur document — genres et
        personnes y sont déjà, il n'y a rien à recalculer.
        """
        if self._client is None or not self.active or not cles:
            return None
        try:
            reponse = await self._client.post(
                f"/{univers.alias_recherche}/_mget",
                json={"ids": [str(cle) for cle in cles], "_source": ["genres", "personnes"]},
            )
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning("Elasticsearch indisponible (%s) — affinités sautées.", exc)
            return None
        return [
            document["_source"]
            for document in reponse.json().get("docs") or []
            if document.get("found")
        ]

    async def titres(self, univers: Univers, cles: list[int], *, langue: str) -> dict[int, str]:
        """Le titre de chaque vignette dans la langue demandée.

        Les projections Postgres ne portent qu'un titre — celui de la
        collecte, en français. Ce que quelqu'un a classé doit pourtant se
        relire dans SA langue : sans ce détour, « Ma liste » rendait des
        titres français à un lecteur arabophone, exactement le défaut qui
        rendait la recherche incompréhensible.

        ES absent : un dictionnaire vide, et l'appelant garde ses titres de
        projection. Une liste dans la mauvaise langue reste meilleure qu'une
        page d'erreur.
        """
        if self._client is None or not self.active or not cles:
            return {}
        champ = champ_titres(langue)
        try:
            reponse = await self._client.post(
                f"/{univers.alias_recherche}/_mget",
                json={"ids": [str(cle) for cle in cles], "_source": [champ]},
            )
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning("Elasticsearch indisponible (%s) — titres non localisés.", exc)
            return {}
        trouves: dict[int, str] = {}
        for document in reponse.json().get("docs") or []:
            if not document.get("found"):
                continue
            valeurs = (document.get("_source") or {}).get(champ) or []
            if valeurs:
                trouves[int(document["_id"])] = valeurs[0]
        return trouves

    async def affinites(
        self,
        univers: Univers,
        *,
        genres: list[str],
        personnes: list[str],
        exclus: list[int],
        taille: int,
    ) -> list[int] | None:
        """Les œuvres qui partagent les genres ou les gens de ce qu'on a aimé.

        C'est le filet du moteur de suggestions, et le seul étage qui ait
        toujours de la matière : un genre et une distribution, toute œuvre
        collectée en a — là où être citée par un membre ou porter une
        empreinte notée reste l'exception.

        Le classement est celui de la recherche : la pertinence (combien de
        genres et de noms en commun) multipliée par la note bayésienne.
        `has_poster` est exigé — on ne propose pas une œuvre qu'on ne peut
        pas montrer.
        """
        if self._client is None or not self.active:
            return None
        devrait: list[dict[str, Any]] = []
        if genres:
            # Un `terms` compte un point par genre partagé : deux genres en
            # commun passent devant un seul.
            devrait += [{"term": {"genres": genre}} for genre in genres]
        if personnes:
            # La phrase entière : « Emilia Clarke » ne doit pas matcher toutes
            # les Clarke du catalogue.
            devrait += [
                {"match_phrase": {"personnes": {"query": nom, "boost": 2.0}}} for nom in personnes
            ]
        if not devrait:
            return []

        corps: dict[str, Any] = {
            "query": {
                "function_score": {
                    "query": {
                        "bool": {
                            "should": devrait,
                            "minimum_should_match": 1,
                            "filter": [
                                {"term": {"fiche": True}},
                                {"term": {"has_poster": True}},
                            ],
                            "must_not": [{"ids": {"values": [str(cle) for cle in exclus]}}],
                        }
                    },
                    "field_value_factor": {
                        "field": "note_bayes",
                        "missing": 5.0,
                        "modifier": "none",
                    },
                    "boost_mode": "multiply",
                }
            },
            "size": taille,
            "_source": False,
            "track_total_hits": False,
        }
        try:
            reponse = await self._client.post(f"/{univers.alias_recherche}/_search", json=corps)
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning("Elasticsearch indisponible (%s) — affinités sautées.", exc)
            return None
        return [int(hit["_id"]) for hit in reponse.json()["hits"]["hits"]]

    async def page(
        self,
        univers: Univers,
        texte: str,
        *,
        taille: int,
        depuis: int = 0,
        langue: str = LANGUE_DEFAUT,
        filtres: dict[str, Sequence[str]] | None = None,
    ) -> PageIds | None:
        """Une page de résultats classés, ou `None` si ES ne peut pas répondre
        — jamais une exception : l'appelant a toujours son chemin SQL.

        Les ids rendus sont ceux des vignettes : id TMDB pour séries et films,
        pivot pour les livres — exactement la clé de `univers.card_view`.
        """
        if self._client is None or not self.active:
            return None
        if depuis + taille > FENETRE_MAX:
            # Pas une panne : une demande hors fenêtre. On le dit en rendant
            # une page vide plutôt qu'en ouvrant le disjoncteur.
            return PageIds(ids=[], total=depuis, tronque=True)
        try:
            reponse = await self._client.post(
                f"/{univers.alias_recherche}/_search",
                json=corps_recherche(
                    texte,
                    taille=taille,
                    depuis=depuis,
                    langue=langue,
                    filtres=filtres,
                ),
            )
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            # Index absent compris : tant que `fiv-admin search reindex` n'a
            # pas tourné, l'alias n'existe pas, et la bonne réponse est le
            # repli SQL — avec le remède dans le journal, pas une page d'erreur.
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning(
                "Elasticsearch indisponible (%s) — repli SQL pendant %.0f s. "
                "Si l'index n'existe pas : `fiv-admin search reindex`.",
                exc,
                DISJONCTEUR_SECONDES,
            )
            return None
        donnees = reponse.json()
        total = int(donnees["hits"]["total"]["value"])
        champ = champ_titres(langue)
        return PageIds(
            ids=[int(hit["_id"]) for hit in donnees["hits"]["hits"]],
            # Le titre dans la langue demandée, quand l'œuvre en a un. La
            # route s'en sert pour remplacer celui de la projection : afficher
            # un titre français à qui cherche en arabe est ce qui rendait la
            # liste incompréhensible.
            titres={
                int(hit["_id"]): (hit.get("_source") or {}).get(champ, [None])[0]
                for hit in donnees["hits"]["hits"]
                if (hit.get("_source") or {}).get(champ)
            },
            total=total,
            # `gte` : ES a arrêté de compter à TOTAL_MAX. Le composant en
            # déduit « au moins », il ne l'affiche pas comme un décompte.
            tronque=donnees["hits"]["total"].get("relation") == "gte",
        )

    async def par_personne(
        self, univers: Univers, nom: str, *, depuis: int = 0, taille: int = 10
    ) -> PageIds | None:
        """Les œuvres dont le champ `personnes` porte ce nom.

        Le repli de la filmographie quand le graphe n'est pas là. `match_phrase`
        et non `match` : « Emilia Clarke » ne doit pas rendre toutes les Clarke
        du catalogue. Le classement reste celui de la maison — la note
        bayésienne — parce qu'à filmographie égale on montre d'abord ce qui est
        le mieux tenu.
        """
        if self._client is None or not self.active:
            return None
        corps = {
            "query": {
                "function_score": {
                    "query": {
                        "bool": {
                            "must": [{"match_phrase": {"personnes": nom}}],
                            "filter": [{"term": {"fiche": True}}],
                        }
                    },
                    "field_value_factor": {
                        "field": "note_bayes",
                        "missing": 5.0,
                        "modifier": "none",
                    },
                    "boost_mode": "multiply",
                }
            },
            "from": depuis,
            "size": taille,
            "_source": False,
            "track_total_hits": TOTAL_MAX,
        }
        try:
            reponse = await self._client.post(f"/{univers.alias_recherche}/_search", json=corps)
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning("Elasticsearch indisponible (%s) — pas de filmographie.", exc)
            return None
        donnees = reponse.json()
        return PageIds(
            ids=[int(hit["_id"]) for hit in donnees["hits"]["hits"]],
            total=int(donnees["hits"]["total"]["value"]),
            tronque=donnees["hits"]["total"].get("relation") == "gte",
        )

    async def facettes(
        self, univers: Univers, *, langue: str = LANGUE_DEFAUT, taille: int = 40
    ) -> dict[str, list[Facette]] | None:
        """Les valeurs présentes de CHAQUE dimension de l'univers, avec leur
        nombre — en une seule requête, agrégations parallèles.

        Une agrégation `terms` sur un champ `keyword` : les doc values sont
        déjà en mémoire, ça se compte en millisecondes même sur 1,2 M de
        documents. C'est LA bonne source pour peupler des cases à cocher —
        elle montre ce que le catalogue contient vraiment, là où une liste
        figée dans le code divergerait au premier genre ajouté par TMDB ou à
        la première plateforme qui perd ses droits.

        `fiche: true`, comme la recherche : proposer un filtre qui ne rendrait
        rien serait pire que ne pas le proposer.
        """
        if self._client is None or not self.active:
            return None
        aggs = {
            dimension.champ: {"terms": {"field": dimension.champ_index(langue), "size": taille}}
            for dimension in univers.dimensions
        }
        try:
            reponse = await self._client.post(
                f"/{univers.alias_recherche}/_search",
                json={
                    "size": 0,
                    "query": {"bool": {"filter": [{"term": {"fiche": True}}]}},
                    "aggs": aggs,
                },
            )
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning("Elasticsearch indisponible (%s) — pas de facettes.", exc)
            return None
        agregations = reponse.json().get("aggregations") or {}
        return {
            champ: [
                Facette(valeur=panier["key"], nombre=panier["doc_count"])
                for panier in (agregations.get(champ) or {}).get("buckets") or []
            ]
            for champ in aggs
        }
