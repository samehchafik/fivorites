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
from collections.abc import Callable
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
    filtres: list[dict[str, Any]] = []
    if fiche is not None:
        filtres.append({"term": {"fiche": fiche}})
    if with_poster:
        filtres.append({"term": {"has_poster": True}})
    if with_overview:
        filtres.append({"term": {"has_overview": True}})
    if min_popularity is not None:
        filtres.append({"range": {"popularity": {"gte": min_popularity}}})

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
        union all
        -- Les œuvres projetées SANS ligne d'inventaire. Le cas est marginal —
        -- import manuel, fixture, export partiel — mais la grille les montre,
        -- puisqu'elle lit la projection : une recherche qui ne les verrait pas
        -- ferait « disparaître » une vignette pourtant affichable.
        select v.id, null, null, null
        from {vue} v
        where not exists (
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


def parametres_extraction(media: Media) -> dict[str, Any]:
    return {"source": SOURCE, "kind": media.kind, "univers": media.univers}


def construire_doc(row: dict[str, Any], univers: str) -> dict[str, Any]:
    """Une ligne d'extraction → un document. Les absences sont omises, pas
    envoyées à `null` : c'est autant de place gagnée dans `_source`."""
    titres: list[str] = list(row.get("titres") or [])
    for titre in (row.get("name"), row.get("original_name"), row.get("nom_inventaire")):
        if titre and titre not in titres:
            titres.append(titre)

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


async def reindexer(
    conn: psycopg.AsyncConnection,
    http: httpx.AsyncClient,
    media: Media,
    *,
    lot: int = 500,
    avancement: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Reconstruit l'index d'un univers et bascule son alias, sans coupure.

    L'index n'est jamais mis à jour au fil de l'eau : il se reconstruit en
    entier, comme la projection de vignettes — après une passe de collecte, ou
    quand le mapping change. C'est ce qui autorise `force_merge` en un seul
    segment : l'index est en lecture seule de fait, autant le compacter.
    """
    alias = alias_de(media)
    nom = f"{alias}-{time.strftime('%Y%m%d%H%M%S')}"

    reponse = await http.put(f"/{nom}", json=definition_index(media.univers))
    reponse.raise_for_status()

    total = 0
    # Curseur serveur : le catalogue entier ne tient pas en mémoire, et le
    # bloc de transaction évite qu'un `with hold` matérialise le résultat.
    async with (
        conn.transaction(),
        conn.cursor(name="es_extraction", row_factory=dict_row) as cur,
    ):
        cur.itersize = lot
        await cur.execute(requete_extraction(media), parametres_extraction(media))
        paquet: list[dict[str, Any]] = []
        async for row in cur:
            paquet.append(construire_doc(row, media.univers))
            if len(paquet) >= lot:
                await _bulk(http, nom, paquet)
                total += len(paquet)
                paquet = []
                if avancement is not None:
                    avancement(total)
        if paquet:
            await _bulk(http, nom, paquet)
            total += len(paquet)

    # Un seul segment : l'index ne recevra plus une écriture avant d'être
    # remplacé, et le compactage rend la recherche plus rapide et le disque
    # plus petit — ce qui compte à 1,5 M de documents par univers.
    await http.post(f"/{nom}/_refresh")
    reponse = await http.post(f"/{nom}/_forcemerge?max_num_segments=1")
    reponse.raise_for_status()
    reponse = await http.put(f"/{nom}/_settings", json={"index": {"refresh_interval": "30s"}})
    reponse.raise_for_status()

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
