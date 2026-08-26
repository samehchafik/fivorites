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
from typing import Any

import httpx

from fiv_webapp.univers import Univers

log = logging.getLogger(__name__)

# Après un échec (connexion refusée, index absent…), ES est écarté pendant ce
# délai : la recherche retombe sur le SQL sans retenter à chaque frappe.
DISJONCTEUR_SECONDES = 30.0


def corps_recherche(texte: str, *, taille: int) -> dict[str, Any]:
    """Le corps `_search` d'une frappe du composant.

    Quatre portes d'entrée, toutes multipliées par la note bayésienne
    précalculée dans le document — jamais `popularity`, biais occidental
    mesuré :

    * `match` sur les préfixes des titres, `operator: and` — le filet ;
    * `match_phrase` sur les mots entiers, boostée — « game of thrones » tapé
      en entier passe devant tout ce qui ne fait que commencer pareil ;
    * les **personnes** (distribution, réalisateurs, créateurs, auteurs) —
      un nom tapé rend sa filmographie ou sa bibliographie ;
    * les **genres**, avec les synonymes posés à l'index (« policier » →
      Crime) — taper un genre devient un parcours de l'univers, classé par
      la note, jamais devant un titre qui matche.
    """
    return {
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"titres": {"query": texte, "operator": "and"}}},
                            {"match_phrase": {"titres.exact": {"query": texte, "boost": 3.0}}},
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
                        "filter": [{"term": {"fiche": True}}],
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
        "size": taille,
        # Les documents restent chez ES : seuls les `_id` remontent, Postgres
        # hydrate les cartes — une seule source de vérité pour l'affichage.
        "_source": False,
        "track_total_hits": False,
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

    async def ids(self, univers: Univers, texte: str, *, taille: int) -> list[int] | None:
        """Les ids classés d'une frappe, ou `None` si ES ne peut pas répondre
        — jamais une exception : l'appelant a toujours son chemin SQL.

        Les ids rendus sont ceux des vignettes : id TMDB pour séries et films,
        pivot pour les livres — exactement la clé de `univers.card_view`.
        """
        if self._client is None or not self.active:
            return None
        try:
            reponse = await self._client.post(
                f"/{univers.alias_recherche}/_search",
                json=corps_recherche(texte, taille=taille),
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
        return [int(hit["_id"]) for hit in donnees["hits"]["hits"]]
