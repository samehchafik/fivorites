"""La recherche plein texte du catalogue, servie par Elasticsearch.

Ce que ce module remplace : un `ILIKE '%…%'` avec joker en tête, donc un
balayage complet de 1,2 million de films à chaque frappe, sur deux champs
seulement — alors que le brut porte les titres dans ~45 langues
(`translations`) et les titres alternatifs. « Le Trône de fer » était
introuvable ; seul « Game of Thrones » répondait.

L'architecture, et pourquoi :

* **Un index par univers** (`catalog-series`, `catalog-movies`), pas un index
  commun. Les ids TMDB se chevauchent entre films et séries (1399 = *Game of
  Thrones* ET un film) : un index par univers permet d'employer l'id TMDB comme
  `_id`, celui que toutes les routes manipulent. C'est aussi ce qui laisse
  chaque univers se réindexer sans toucher l'autre, et ce qui accueillera
  `books`, `bd`, `musics` — dont les champs divergeront — sans mapping
  fourre-tout.
* **Les index physiques sont horodatés et servis par un alias.** La
  réindexation construit à côté, bascule l'alias, supprime l'ancien : zéro
  coupure — le même contrat que `refresh materialized view concurrently`.
* **Le document est minimal** : ce qui sert à chercher (les titres, toutes
  langues confondues, aplatis dans un seul champ), à filtrer (univers, affiche,
  synopsis, popularité) et à classer (la note bayésienne, précalculée). Tout le
  reste — synopsis, visuels, distribution — reste dans Postgres : ES rend des
  ids classés, Postgres hydrate la page. Pas de `nested` : il n'y a rien à
  corréler entre sous-champs, et chaque objet nested serait un document Lucene
  de plus.
* **La frappe est servie par un `edge_ngram` posé à l'indexation** (préfixes de
  2 à 20 caractères), jamais par un joker à la requête : la recherche devient
  un `match` sur des termes exacts, quelques millisecondes sur 1,5 M de
  documents. `asciifolding` fait trouver « Trône » en tapant « trone ».
* **Le classement multiplie la pertinence par la note bayésienne** — la même
  formule que le tri de la grille (voir `catalog.py`), figée dans le document à
  l'indexation plutôt que recalculée à chaque requête. Jamais `popularity` : le
  dictionnaire de données la disqualifie, biais occidental mesuré (facteur 6
  contre l'écriture arabe), et un boost l'importerait tel quel dans chaque
  liste de résultats.

ES reste facultatif : chaque route qui l'interroge retombe sur son `ILIKE`
historique quand il ne répond pas, et un disjoncteur évite de payer une
tentative de connexion à chaque frappe pendant une panne.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fiv_admin.media import Media

log = logging.getLogger(__name__)

SOURCE = "tmdb"

# Après un échec (connexion refusée, index absent…), ES est écarté pendant ce
# délai : la grille retombe sur le SQL sans retenter à chaque frappe.
DISJONCTEUR_SECONDES = 30.0

# ES refuse de paginer au-delà de `from + size = 10 000` (et il a raison :
# personne ne lit la 400e page d'une recherche). Au-delà, on laisse le SQL
# faire — sans compter ça comme une panne.
FENETRE_MAX = 10_000

# Le plafond d'ids rendus pour le tableau d'acquisition. Son filtre d'état
# (`collected`, `error`…) se lit dans `fetch_state`, qui bouge à chaque passe
# de collecte : l'indexer serait le figer. ES classe donc les N meilleurs ids
# par pertinence, et le SQL applique l'état dessus. Une recherche assez vague
# pour dépasser ce plafond a d'abord besoin d'être précisée, pas paginée.
ACQUISITION_MAX_IDS = 2000


def alias_de(media: Media) -> str:
    """L'alias servi aux requêtes ; les index physiques sont horodatés."""
    return f"catalog-{media.univers}"


def definition_index(univers: str) -> dict[str, Any]:
    """Réglages et mapping d'un index d'univers.

    `dynamic: strict` : un champ qui n'est pas décidé ici n'entre pas — c'est
    la seule protection contre un document enrichi « en passant » qui ferait
    grossir l'index sans que rien ne le signale.

    Les champs d'affichage (`name`, `poster_path`…) sont stockés mais ni
    indexés ni chargés en mémoire colonne (`index: false, doc_values: false`) :
    ils ne coûtent que leur place dans `_source`.
    """
    return {
        "settings": {
            # 1,5 M de documents minimaux : un seul shard, sans réplique — un
            # nœud unique n'aurait où la placer, et elle doublerait le disque.
            "number_of_shards": 1,
            "number_of_replicas": 0,
            # Pendant la construction rien n'est cherché : pas de refresh du
            # tout. La réindexation le rétablit avant de basculer l'alias.
            "refresh_interval": "-1",
            "analysis": {
                "filter": {
                    # Les préfixes, calculés à l'indexation : c'est ce qui rend
                    # la frappe instantanée — la requête n'a plus qu'à matcher
                    # des termes exacts. `preserve_original` garde aussi le mot
                    # entier, pour les mots plus longs que `max_gram`.
                    "prefixes": {
                        "type": "edge_ngram",
                        "min_gram": 2,
                        "max_gram": 20,
                        "preserve_original": True,
                    }
                },
                "analyzer": {
                    "titres_index": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding", "prefixes"],
                    },
                    # Le même sans préfixes : ce que l'utilisateur a tapé se
                    # cherche tel quel, ce sont les index qui portent les
                    # troncatures.
                    "titres_recherche": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    },
                },
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "univers": {"type": "keyword"},
                "id_tmdb": {"type": "long"},
                # Le pivot d'identité (`sourcing.oeuvre.id`), embarqué pour le
                # jour où l'index servira des œuvres sans id TMDB — les ~44 700
                # entrées Wikidata d'aujourd'hui n'y sont pas encore.
                "oeuvre_id": {"type": "long", "index": False},
                # Tous les titres, toutes langues confondues — nom courant,
                # titre original, titres alternatifs, traductions. Un seul
                # champ : savoir quelle langue a matché n'intéresse personne,
                # et c'est ce qui dispense de tout `nested`.
                "titres": {
                    "type": "text",
                    "analyzer": "titres_index",
                    "search_analyzer": "titres_recherche",
                    # Les normes pondèrent par la longueur du champ ; ici elle
                    # ne mesure que le nombre de langues traduites. Les couper
                    # économise un octet par document et un biais.
                    "norms": False,
                    "fields": {
                        # Les mots entiers, sans préfixes : sert à booster le
                        # match exact au-dessus des simples débuts de mots.
                        "exact": {
                            "type": "text",
                            "analyzer": "titres_recherche",
                            "norms": False,
                        }
                    },
                },
                "name": {"type": "keyword", "index": False, "doc_values": False},
                "original_name": {"type": "keyword", "index": False, "doc_values": False},
                # Le tri alphabétique du parcours : `coalesce(name, original)`
                # plié (minuscules, sans accents) à l'indexation — un keyword
                # trié par ES l'est en points de code, le pliage rapproche
                # l'ordre de celui d'une collation SQL.
                "nom_tri": {"type": "keyword", "index": False},
                "annee": {"type": "short"},
                "first_air_date": {"type": "date", "format": "strict_date"},
                "fetched_at": {"type": "date"},
                "status": {"type": "keyword"},
                "original_language": {"type": "keyword"},
                "genres": {"type": "keyword"},
                "origin_country": {"type": "keyword"},
                # La moyenne bayésienne de `catalog.py`, figée à l'indexation :
                # le classement n'a plus rien à calculer.
                "note_bayes": {"type": "half_float"},
                "vote_count": {"type": "integer"},
                # Filtre seulement (popularité minimale) — jamais un boost,
                # voir l'en-tête du module.
                "popularity": {"type": "float"},
                "adult": {"type": "boolean"},
                # Une fiche a été collectée : le document correspond à une
                # ligne de la projection de vignettes. La grille filtre dessus,
                # le tableau d'acquisition non.
                "fiche": {"type": "boolean"},
                "has_poster": {"type": "boolean"},
                "has_overview": {"type": "boolean"},
                "poster_path": {"type": "keyword", "index": False, "doc_values": False},
            },
        },
    }


# ---------------------------------------------------------------------------
# La requête
# ---------------------------------------------------------------------------


def _filtres(
    *,
    fiche: bool | None = None,
    with_poster: bool = False,
    with_overview: bool = False,
    min_popularity: float | None = None,
) -> list[dict[str, Any]]:
    """Les filtres communs à la recherche et au parcours — les mêmes clauses
    que le `where` SQL qu'ils remplacent."""
    filtres: list[dict[str, Any]] = []
    if fiche is not None:
        filtres.append({"term": {"fiche": fiche}})
    if with_poster:
        filtres.append({"term": {"has_poster": True}})
    if with_overview:
        filtres.append({"term": {"has_overview": True}})
    if min_popularity is not None:
        filtres.append({"range": {"popularity": {"gte": min_popularity}}})
    return filtres


# Les tris que les routes connaissent → le champ ES qui les porte. Les clés
# sont celles de `CARD_SORTS` (grille) et `SORTS` (acquisition) : la liste
# reste fermée, comme côté SQL.
TRIS: dict[str, str] = {
    "air_date": "first_air_date",
    "air_year": "annee",
    "name": "nom_tri",
    "popularity": "popularity",
    "rating": "note_bayes",
    "fetched": "fetched_at",
    "id": "id_tmdb",
}


def corps_liste(
    criteres: Sequence[tuple[str, bool]],
    *,
    tiebreak_descendant: bool,
    fiche: bool | None = None,
    with_poster: bool = False,
    with_overview: bool = False,
    min_popularity: float | None = None,
    taille: int,
    depuis: int = 0,
) -> dict[str, Any]:
    """Le corps `_search` d'un parcours sans texte : filtres, tri, pagination.

    C'est ce qui fait d'ES le moteur de TOUTES les listes, pas seulement de la
    recherche : les filtres et le tri sont servis par les doc values, et le
    total — qui coûtait un `count(*)` complet à chaque page en SQL — est
    rendu gratuitement avec la page.

    `missing: _last` sur chaque critère : la traduction exacte du
    `nulls last` du SQL — une œuvre sans note n'est pas « moyennement notée »,
    elle va en fin de liste dans les deux sens. Le départage final sur l'id
    est celui des requêtes SQL, même sens : sans lui, deux œuvres égales
    pourraient changer de place entre deux pages.
    """
    tri: list[dict[str, Any]] = [
        {TRIS[cle]: {"order": "desc" if descendant else "asc", "missing": "_last"}}
        for cle, descendant in criteres
    ]
    tri.append({"id_tmdb": {"order": "desc" if tiebreak_descendant else "asc"}})
    return {
        "query": {
            "bool": {
                "filter": _filtres(
                    fiche=fiche,
                    with_poster=with_poster,
                    with_overview=with_overview,
                    min_popularity=min_popularity,
                )
            }
        },
        "sort": tri,
        "from": depuis,
        "size": taille,
        "_source": False,
        "track_total_hits": True,
    }


def corps_recherche(
    texte: str,
    *,
    fiche: bool | None = None,
    with_poster: bool = False,
    with_overview: bool = False,
    min_popularity: float | None = None,
    taille: int,
    depuis: int = 0,
) -> dict[str, Any]:
    """Le corps `_search` d'une frappe utilisateur.

    Deux étages de pertinence, tous deux multipliés par la note bayésienne :

    * `match` sur les préfixes, `operator: and` — chaque mot tapé doit ouvrir
      un mot d'un titre ; c'est le filet.
    * `match_phrase` sur les mots entiers, boostée — « game of thrones » tapé
      en entier passe devant tout ce qui ne fait que commencer pareil.

    Un texte entièrement numérique cherche aussi l'id TMDB : c'est le contrat
    du champ de recherche depuis toujours (« titre ou id TMDB »).
    """
    filtres = _filtres(
        fiche=fiche,
        with_poster=with_poster,
        with_overview=with_overview,
        min_popularity=min_popularity,
    )

    devrait: list[dict[str, Any]] = [
        {"match": {"titres": {"query": texte, "operator": "and"}}},
        {"match_phrase": {"titres.exact": {"query": texte, "boost": 3.0}}},
    ]
    if texte.isdigit():
        devrait.append({"term": {"id_tmdb": {"value": int(texte), "boost": 10.0}}})

    return {
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "should": devrait,
                        "minimum_should_match": 1,
                        "filter": filtres,
                    }
                },
                # Une œuvre sans note vaut 5 — sous la moyenne de 6,5, donc
                # derrière les œuvres notées, mais pas invisible.
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
        # Les documents restent chez ES : seuls les `_id` remontent, Postgres
        # hydrate la page — une seule source de vérité pour l'affichage.
        "_source": False,
        "track_total_hits": True,
    }


@dataclass(frozen=True, slots=True)
class PageIds:
    """Ce qu'ES rend aux routes : des ids TMDB classés, et le total du filtre."""

    ids: list[int]
    total: int


class Recherche:
    """Le client HTTP du service, avec son disjoncteur.

    httpx plutôt qu'un client officiel : quatre routes REST suffisent, et le
    module en dépend déjà. `url` vide = recherche désactivée, les routes s'en
    tiennent au SQL.
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

    async def _search(self, alias: str, corps: dict[str, Any]) -> PageIds | None:
        """Une recherche, ou `None` si ES ne peut pas répondre — jamais une
        exception : l'appelant a toujours son chemin SQL."""
        if self._client is None or not self.active:
            return None
        try:
            reponse = await self._client.post(f"/{alias}/_search", json=corps)
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            # Index absent compris : tant que `search reindex` n'a pas tourné,
            # l'alias n'existe pas, et la bonne réponse est le repli SQL — avec
            # le remède dans le journal, pas une page d'erreur.
            self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
            log.warning(
                "Elasticsearch indisponible (%s) — repli SQL pendant %.0f s. "
                "Si l'index n'existe pas : `fiv-admin search reindex`.",
                exc,
                DISJONCTEUR_SECONDES,
            )
            return None
        donnees = reponse.json()
        return PageIds(
            ids=[int(hit["_id"]) for hit in donnees["hits"]["hits"]],
            total=int(donnees["hits"]["total"]["value"]),
        )

    async def page_cards(
        self,
        media: Media,
        texte: str,
        *,
        with_poster: bool = False,
        with_overview: bool = False,
        min_popularity: float | None = None,
        page: int,
        page_size: int,
    ) -> PageIds | None:
        """La page de la grille : ids classés par pertinence, total du filtre.

        `fiche: true` — la grille ne montre que ce qui a une projection, ES
        doit compter pareil.
        """
        depuis = (page - 1) * page_size
        if depuis + page_size > FENETRE_MAX:
            return None
        return await self._search(
            alias_de(media),
            corps_recherche(
                texte,
                fiche=True,
                with_poster=with_poster,
                with_overview=with_overview,
                min_popularity=min_popularity,
                taille=page_size,
                depuis=depuis,
            ),
        )

    async def ids_acquisition(
        self,
        media: Media,
        texte: str,
        *,
        min_popularity: float | None = None,
    ) -> PageIds | None:
        """Les meilleurs ids pour le tableau d'acquisition, catalogue entier.

        Le filtre d'état reste au SQL (voir `ACQUISITION_MAX_IDS`) : ici on ne
        restreint pas à `fiche`, une œuvre jamais collectée doit se trouver.
        """
        page = await self._search(
            alias_de(media),
            corps_recherche(
                texte,
                min_popularity=min_popularity,
                taille=ACQUISITION_MAX_IDS,
            ),
        )
        if page is None:
            return None
        # Le total rendu est plafonné à ce qu'on a vraiment : au-delà, la
        # pagination promettrait des pages que les ids ne couvrent pas.
        return PageIds(ids=page.ids, total=min(page.total, len(page.ids)))

    async def liste_cards(
        self,
        media: Media,
        criteres: Sequence[tuple[str, bool]],
        *,
        with_poster: bool = False,
        with_overview: bool = False,
        min_popularity: float | None = None,
        page: int,
        page_size: int,
    ) -> PageIds | None:
        """Une page de la grille SANS texte : mêmes filtres et mêmes tris que
        le SQL, servis par les doc values — et le total rendu avec la page,
        là où le SQL payait un `count(*)` complet à chaque affichage."""
        depuis = (page - 1) * page_size
        if depuis + page_size > FENETRE_MAX:
            return None
        return await self._search(
            alias_de(media),
            corps_liste(
                criteres,
                # Le même départage que `fetch_cards` : id décroissant.
                tiebreak_descendant=True,
                fiche=True,
                with_poster=with_poster,
                with_overview=with_overview,
                min_popularity=min_popularity,
                taille=page_size,
                depuis=depuis,
            ),
        )

    async def liste_acquisition(
        self,
        media: Media,
        *,
        sort: str,
        descending: bool,
        min_popularity: float | None = None,
        page: int,
        page_size: int,
    ) -> PageIds | None:
        """Une page du tableau d'acquisition sans texte ni filtre d'état.

        Réservée à `status=all` : les autres états vivent dans `fetch_state`
        et restent au SQL. Le tri `fetched` aussi — côté SQL c'est une
        jointure interne qui ne liste que le déjà-regardé, une sémantique
        qu'un `missing: _last` ne reproduit pas.
        """
        depuis = (page - 1) * page_size
        if depuis + page_size > FENETRE_MAX:
            return None
        return await self._search(
            alias_de(media),
            corps_liste(
                [(sort, descending)],
                # Le même départage que `fetch_items` : id croissant.
                tiebreak_descendant=False,
                min_popularity=min_popularity,
                taille=page_size,
                depuis=depuis,
            ),
        )

    async def synchroniser_tout(
        self, conn: psycopg.AsyncConnection
    ) -> dict[str, dict[str, Any]] | None:
        """La synchronisation best-effort des routes : chaque univers rattrapé,
        aucune exception ne sort — un refresh de projection ne doit jamais
        échouer parce qu'ES tousse."""
        from fiv_admin.media import MEDIA

        if self._client is None or not self.active:
            return None
        bilan: dict[str, dict[str, Any]] = {}
        for media in MEDIA.values():
            if media.catalog_table is None:
                continue
            try:
                bilan[media.univers] = await synchroniser(conn, self._client, media)
            except (httpx.HTTPError, RuntimeError) as exc:
                self._coupe_jusqua = time.monotonic() + DISJONCTEUR_SECONDES
                log.warning("synchronisation %s en échec : %s", media.univers, exc)
                bilan[media.univers] = {"alias": alias_de(media), "erreur": str(exc)}
        return bilan


# ---------------------------------------------------------------------------
# L'indexation
# ---------------------------------------------------------------------------

# Une ligne par œuvre de l'inventaire, projection et titres compris.
#
# Les titres viennent du dernier brut de la fiche : racine (`name`/`title` et
# l'original), titres alternatifs, et le nom de CHAQUE traduction — c'est là
# que dort « Le Trône de fer ». Une œuvre jamais collectée n'a que son
# `original_name` d'inventaire : c'est déjà ce que le tableau d'acquisition
# cherchait, et l'index couvre donc tout le catalogue, pas juste le collecté.
#
# La jointure `lateral` sur `raw_source` fait une lecture d'index par œuvre —
# et un détoastage du payload pour les œuvres collectées, ce qui est le vrai
# coût de la réindexation. C'est le prix d'un principe : les traductions ne
# sont jamais portées en projection (voir `catalog.py`), on les relit du brut.
_EXTRACTION = sql.SQL(
    """
    with inventaire as (
        select c.id, c.original_name, c.popularity, c.adult
        from tmdb_catalog c
        where c.univers = %(univers)s
          -- `ids` nul = tout l'univers (réindexation) ; sinon, les seules
          -- œuvres listées (synchronisation incrémentale).
          and (%(ids)s::int[] is null or c.id = any (%(ids)s))
        union all
        -- Les œuvres projetées SANS ligne d'inventaire. Le cas est marginal —
        -- import manuel, fixture, export partiel — mais la grille les montre,
        -- puisqu'elle lit la projection : une recherche qui ne les verrait pas
        -- ferait « disparaître » une vignette pourtant affichable.
        select v.id, null, null, null
        from {vue} v
        where (%(ids)s::int[] is null or v.id = any (%(ids)s))
          and not exists (
            select 1 from tmdb_catalog c where c.univers = %(univers)s and c.id = v.id
        )
    )
    select c.id,
           c.original_name as nom_inventaire,
           c.popularity,
           c.adult,
           o.id as oeuvre_id,
           v.id is not null as fiche,
           v.name,
           v.original_name,
           v.first_air_date,
           extract(year from v.first_air_date)::int as annee,
           v.fetched_at,
           v.status,
           v.original_language,
           v.vote_count,
           {note} as note_bayes,
           nullif(v.poster_path, '') as poster_path,
           nullif(btrim(v.overview), '') is not null as has_overview,
           array(
               select g ->> 'name'
               from jsonb_array_elements(coalesce(v.genres, '[]'::jsonb)) g
               where nullif(btrim(g ->> 'name'), '') is not null
           ) as genres,
           v.origin_country,
           case when rp.payload is null then null else array(
               select distinct btrim(t.titre)
               from (
                   select coalesce(rp.payload ->> 'name', rp.payload ->> 'title') as titre
                   union all
                   select coalesce(rp.payload ->> 'original_name',
                                   rp.payload ->> 'original_title')
                   union all
                   -- Les séries rangent leurs titres alternatifs sous
                   -- `results`, les films sous `titles`. Même contenu.
                   select alt ->> 'title'
                   from jsonb_array_elements(
                       coalesce(rp.payload -> 'alternative_titles' -> 'results',
                                rp.payload -> 'alternative_titles' -> 'titles',
                                '[]'::jsonb)) alt
                   union all
                   select coalesce(tr -> 'data' ->> 'name', tr -> 'data' ->> 'title')
                   from jsonb_array_elements(
                       coalesce(rp.payload -> 'translations' -> 'translations',
                                '[]'::jsonb)) tr
               ) t
               where nullif(btrim(t.titre), '') is not null
           ) end as titres
    from inventaire c
    left join {vue} v on v.id = c.id
    left join oeuvre o on o.univers = %(univers)s and o.id_tmdb = c.id
    left join lateral (
        select r.payload
        from raw_source r
        where r.source = %(source)s and r.kind = %(kind)s and r.source_id = c.id::text
          and r.http_status between 200 and 299 and r.payload is not null
        order by r.fetched_at desc
        limit 1
    ) rp on true
    """
)


def requete_extraction(media: Media) -> sql.Composed:
    """La requête d'extraction d'un univers, prête à exécuter.

    Sortie du corps de `reindexer` pour être testable contre une vraie base :
    les chemins jsonb (`alternative_titles.results` contre `.titles`,
    `translations[].data.name` contre `.title`) sont exactement le genre de
    détail qu'un test unitaire ne peut pas voir.
    """
    # Import local — même raison que dans `reindexer` : éviter le cycle avec
    # `catalog`, qui pourrait un jour importer ce module.
    from fiv_admin.catalog import note_ponderee

    return _EXTRACTION.format(
        vue=sql.Identifier("admin", media.card_view),
        note=note_ponderee("v"),
    )


def parametres_extraction(media: Media, ids: Sequence[int] | None = None) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "kind": media.kind,
        "univers": media.univers,
        "ids": list(ids) if ids is not None else None,
    }


def _plier(texte: str) -> str:
    """Minuscules, sans accents : le tri d'un keyword ES se fait en points de
    code, le pliage le rapproche d'une collation SQL."""
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(caractere)
    )


def construire_doc(row: dict[str, Any], univers: str) -> dict[str, Any]:
    """Une ligne d'extraction → un document. Les absences sont omises, pas
    envoyées à `null` : c'est autant de place gagnée dans `_source`."""
    titres: list[str] = list(row.get("titres") or [])
    for titre in (row.get("name"), row.get("original_name"), row.get("nom_inventaire")):
        if titre and titre not in titres:
            titres.append(titre)
    nom_tri = row.get("name") or row.get("original_name") or row.get("nom_inventaire")

    first_air_date = row.get("first_air_date")
    fetched_at = row.get("fetched_at")
    note = row.get("note_bayes")
    popularity = row.get("popularity")

    doc: dict[str, Any] = {
        "univers": univers,
        "id_tmdb": row["id"],
        "oeuvre_id": row.get("oeuvre_id"),
        "titres": titres or None,
        "name": row.get("name"),
        "original_name": row.get("original_name") or row.get("nom_inventaire"),
        "nom_tri": _plier(nom_tri) if nom_tri else None,
        "annee": row.get("annee"),
        "first_air_date": first_air_date.isoformat() if first_air_date else None,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "status": row.get("status"),
        "original_language": row.get("original_language"),
        "genres": row.get("genres") or None,
        "origin_country": list(row.get("origin_country") or []) or None,
        "note_bayes": round(float(note), 2) if note is not None else None,
        "vote_count": row.get("vote_count"),
        "popularity": round(float(popularity), 3) if popularity is not None else None,
        "adult": row.get("adult"),
        "fiche": bool(row.get("fiche")),
        "has_poster": row.get("poster_path") is not None,
        "has_overview": bool(row.get("has_overview")),
        "poster_path": row.get("poster_path"),
    }
    return {cle: valeur for cle, valeur in doc.items() if valeur is not None}


async def _bulk(http: httpx.AsyncClient, index: str, docs: list[dict[str, Any]]) -> None:
    lignes: list[str] = []
    for doc in docs:
        lignes.append(json.dumps({"index": {"_index": index, "_id": str(doc["id_tmdb"])}}))
        lignes.append(json.dumps(doc, ensure_ascii=False))
    reponse = await http.post(
        "/_bulk",
        content=("\n".join(lignes) + "\n").encode(),
        headers={"content-type": "application/x-ndjson"},
        # Par requête, parce que la synchronisation peut passer par le client
        # des routes, réglé court pour la frappe : un bulk n'est pas une frappe.
        timeout=120.0,
    )
    reponse.raise_for_status()
    corps = reponse.json()
    if corps.get("errors"):
        premiere = next(
            item["index"]["error"] for item in corps["items"] if item["index"].get("error")
        )
        raise RuntimeError(f"bulk refusé par Elasticsearch : {premiere}")


async def _indices_de(http: httpx.AsyncClient, alias: str) -> list[str]:
    reponse = await http.get(f"/_alias/{alias}")
    if reponse.status_code == 404:
        return []
    reponse.raise_for_status()
    return list(reponse.json())


async def _indices_du_prefixe(http: httpx.AsyncClient, alias: str) -> list[str]:
    """Tous les index physiques de l'univers, rattachés à l'alias ou non : une
    réindexation interrompue laisse un orphelin, qu'il faut balayer aussi."""
    reponse = await http.get(f"/_cat/indices/{alias}-*?format=json&h=index")
    reponse.raise_for_status()
    return [ligne["index"] for ligne in reponse.json()]


async def _horloge_base(conn: psycopg.AsyncConnection) -> str:
    """L'heure de la BASE, en ISO : c'est contre elle que `fetch_state` et le
    catalogue sont horodatés — celle du poste peut en diverger."""
    async with conn.cursor() as cur:
        await cur.execute("select now()")
        row = await cur.fetchone()
    return row[0].isoformat()


async def _indexer_extraction(
    conn: psycopg.AsyncConnection,
    http: httpx.AsyncClient,
    index: str,
    media: Media,
    *,
    lot: int,
    ids: Sequence[int] | None = None,
    avancement: Callable[[int], None] | None = None,
) -> int:
    """Extrait (tout l'univers, ou les seuls `ids`) et envoie par lots."""
    total = 0
    # Curseur serveur : le catalogue entier ne tient pas en mémoire, et le
    # bloc de transaction évite qu'un `with hold` matérialise le résultat.
    async with (
        conn.transaction(),
        conn.cursor(name="es_extraction", row_factory=dict_row) as cur,
    ):
        cur.itersize = lot
        await cur.execute(requete_extraction(media), parametres_extraction(media, ids))
        paquet: list[dict[str, Any]] = []
        async for row in cur:
            paquet.append(construire_doc(row, media.univers))
            if len(paquet) >= lot:
                await _bulk(http, index, paquet)
                total += len(paquet)
                paquet = []
                if avancement is not None:
                    avancement(total)
        if paquet:
            await _bulk(http, index, paquet)
            total += len(paquet)
    return total


async def _poser_marqueur(http: httpx.AsyncClient, index: str, horodatage: str) -> None:
    """Le point de reprise de la synchronisation, rangé DANS l'index : il
    meurt avec lui, et un index reconstruit repart donc de son propre début —
    aucun état à tenir ailleurs."""
    reponse = await http.put(
        f"/{index}/_mapping", json={"_meta": {"synced_at": horodatage}}, timeout=30.0
    )
    reponse.raise_for_status()


async def reindexer(
    conn: psycopg.AsyncConnection,
    http: httpx.AsyncClient,
    media: Media,
    *,
    lot: int = 500,
    avancement: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Reconstruit l'index d'un univers et bascule son alias, sans coupure.

    C'est la voie lourde — mapping neuf, catalogue entier — pour la première
    mise en service et les changements de schéma. Au quotidien, `synchroniser`
    rattrape l'index en place sans rien reconstruire.
    """
    alias = alias_de(media)
    nom = f"{alias}-{time.strftime('%Y%m%d%H%M%S')}"

    reponse = await http.put(f"/{nom}", json=definition_index(media.univers))
    reponse.raise_for_status()

    # L'heure de départ, AVANT l'extraction : tout ce qui bouge pendant la
    # construction sera revu par la première synchronisation — un recouvrement
    # plutôt qu'un trou.
    depart = await _horloge_base(conn)
    total = await _indexer_extraction(conn, http, nom, media, lot=lot, avancement=avancement)

    # Un seul segment : quotidiennement l'index ne reçoit que le filet de la
    # synchronisation, et le compactage rend la recherche plus rapide et le
    # disque plus petit — ce qui compte à 1,5 M de documents par univers.
    await http.post(f"/{nom}/_refresh")
    reponse = await http.post(f"/{nom}/_forcemerge?max_num_segments=1")
    reponse.raise_for_status()
    reponse = await http.put(f"/{nom}/_settings", json={"index": {"refresh_interval": "30s"}})
    reponse.raise_for_status()
    await _poser_marqueur(http, nom, depart)

    servis = await _indices_de(http, alias)
    actions = [{"remove": {"index": ancien, "alias": alias}} for ancien in servis]
    actions.append({"add": {"index": nom, "alias": alias}})
    reponse = await http.post("/_aliases", json={"actions": actions})
    reponse.raise_for_status()
    # Le balai passe sur tout le préfixe, pas seulement sur ce que l'alias
    # servait : une réindexation interrompue laisse un index orphelin, et le
    # laisser s'accumuler mangerait le disque en silence.
    anciens = [i for i in await _indices_du_prefixe(http, alias) if i != nom]
    for ancien in anciens:
        await http.delete(f"/{ancien}")

    return {"index": nom, "alias": alias, "documents": total, "remplaces": anciens}


# Ce qui a bougé depuis le marqueur : les fiches (re)collectées — une passe de
# `backfill` les horodate dans `fetch_state` — et les entrées d'inventaire
# nouvelles ou signalées changées par `tmdb export` / `tmdb changes`.
#
# Volontairement PAS `last_seen_at` : l'export quotidien retouche cette
# colonne sur tout le catalogue, et la prendre reviendrait à tout réextraire
# chaque nuit — la synchronisation redeviendrait la réindexation qu'elle
# remplace.
_IDS_CHANGES = """
    select distinct x.id from (
        select s.source_id::int as id
        from fetch_state s
        where s.source = %(source)s and s.kind = %(kind)s
          and s.source_id ~ '^[0-9]+$'
          and s.last_fetched_at > %(depuis)s::timestamptz
        union all
        select c.id
        from tmdb_catalog c
        where c.univers = %(univers)s
          and (c.first_seen_at > %(depuis)s::timestamptz
               or coalesce(c.changed_at, '-infinity') > %(depuis)s::timestamptz)
    ) x
"""


async def synchroniser(
    conn: psycopg.AsyncConnection,
    http: httpx.AsyncClient,
    media: Media,
    *,
    lot: int = 500,
) -> dict[str, Any]:
    """Rattrape l'index vivant : upsert de ce qui a bougé depuis le marqueur.

    C'est la voie du quotidien — « les données importées des sources arrivent
    directement dans ES » : après une passe de collecte (et le refresh des
    projections, qui porte les métadonnées des vignettes), on rejoue
    l'extraction sur les seules œuvres changées, et le `_id` fait de chaque
    envoi une création ou une mise à jour, indifféremment.

    Ce qu'elle ne fait pas : retirer une œuvre disparue du catalogue (rare —
    la réindexation purge), ni rattraper un changement de mapping (la
    réindexation, again). Sans marqueur, elle refuse et le dit.
    """
    alias = alias_de(media)
    vivants = await _indices_de(http, alias)
    if not vivants:
        return {"alias": alias, "erreur": "aucun index — lancer `search reindex`"}
    nom = vivants[0]

    reponse = await http.get(f"/{nom}/_mapping", timeout=30.0)
    reponse.raise_for_status()
    meta = reponse.json()[nom]["mappings"].get("_meta") or {}
    depuis = meta.get("synced_at")
    if not depuis:
        # Un index d'avant les marqueurs : impossible de savoir ce qui manque.
        return {"alias": alias, "erreur": "index sans marqueur — lancer `search reindex`"}

    # L'heure AVANT la lecture des ids : ce qui bouge pendant l'envoi sera
    # revu au prochain passage — recouvrement, jamais de trou.
    maintenant = await _horloge_base(conn)
    async with conn.cursor() as cur:
        await cur.execute(
            _IDS_CHANGES,
            {
                "source": SOURCE,
                "kind": media.kind,
                "univers": media.univers,
                "depuis": depuis,
            },
        )
        ids = [row[0] for row in await cur.fetchall()]

    total = 0
    if ids:
        total = await _indexer_extraction(conn, http, nom, media, lot=lot, ids=ids)
        await http.post(f"/{nom}/_refresh", timeout=60.0)
    await _poser_marqueur(http, nom, maintenant)

    return {"alias": alias, "index": nom, "changees": len(ids), "documents": total}


async def etat(http: httpx.AsyncClient) -> dict[str, Any]:
    """La santé du service et les comptes par alias — ce que `search status`
    et `doctor` affichent."""
    sante = (await http.get("/_cluster/health")).json()
    indices: dict[str, Any] = {}
    for ligne in (await http.get("/_cat/indices/catalog-*?format=json")).json():
        indices[ligne["index"]] = {
            "documents": int(ligne["docs.count"] or 0),
            "taille": ligne["store.size"],
        }
    return {"sante": sante.get("status"), "indices": indices}
