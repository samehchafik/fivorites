"""La navigation dans ce qui a été collecté : vignettes, fiche, saisons.

Deux régimes de lecture, et la distinction est délibérée.

* **La grille** lit `admin.tv_card`, la projection plate (voir
  `002_admin_cards.sql`). Elle est rapide et légèrement en retard.
* **La fiche et les saisons** relisent `sourcing.raw_source`. Ce qu'on ouvre est
  donc toujours l'état réel du stockage, jamais un résumé recalculé.

C'est aussi la frontière du langage : la grille est monolingue par nature (une
vignette, un titre), tandis que la fiche est l'endroit où le sélecteur de langue
prend tout son sens — les synopsis d'épisode ne sont traduits que parce qu'on a
redemandé la saison entière dans cette langue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

SOURCE = "tmdb"
KIND_SERIES = "tv"
KIND_SEASON = "tv_season"

# Tris de la grille. Liste fermée : la clé vient de la requête HTTP, jamais le
# nom de colonne.
CARD_SORTS: dict[str, sql.SQL] = {
    # Le défaut demandé : de la plus récente à la plus ancienne.
    "air_date": sql.SQL("v.first_air_date"),
    "name": sql.SQL("coalesce(v.name, v.original_name)"),
    "popularity": sql.SQL("c.popularity"),
    "fetched": sql.SQL("v.fetched_at"),
}

# Combien de visuels et de comédiens la fiche rapporte. Le brut en contient
# souvent des centaines ; les envoyer tous ferait peser une modale plus lourd
# que toute la grille.
GALLERY_LIMIT = 18
CAST_LIMIT = 30


@dataclass(frozen=True, slots=True)
class CardQuery:
    lang: str
    search: str | None = None
    min_popularity: float | None = None
    sort: str = "air_date"
    descending: bool = True
    page: int = 1
    page_size: int = 24

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


async def fetch_cards(
    conn: psycopg.AsyncConnection, q: CardQuery
) -> tuple[list[dict[str, Any]], int]:
    """Une page de vignettes, et le total du filtre."""
    params: dict[str, Any] = {
        "source": SOURCE,
        "part_kind": KIND_SEASON,
        "limit": q.page_size,
        "offset": q.offset,
        "search": q.search or None,
        "like": f"%{q.search}%" if q.search else None,
        "search_id": int(q.search) if q.search and q.search.isdigit() else None,
        "min_popularity": q.min_popularity,
    }

    where = sql.SQL(" and ").join(
        [
            sql.SQL(
                "(%(search)s::text is null"
                " or v.name ilike %(like)s"
                " or v.original_name ilike %(like)s"
                " or v.id = %(search_id)s::int)"
            ),
            sql.SQL("(%(min_popularity)s::real is null or c.popularity >= %(min_popularity)s)"),
        ]
    )

    direction = sql.SQL("desc") if q.descending else sql.SQL("asc")
    order = sql.SQL("{} {} nulls last, v.id desc").format(CARD_SORTS[q.sort], direction)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql.SQL(
                """
                select count(*) as total
                from admin.tv_card v
                left join tmdb_catalog c on c.id = v.id
                where {where}
                """
            ).format(where=where),
            params,
        )
        row = await cur.fetchone()
        total = int(row["total"]) if row else 0

        await cur.execute(
            sql.SQL(
                """
                with page as (
                    select v.id, v.name, v.original_name, v.overview, v.poster_path,
                           v.backdrop_path, v.status, v.original_language,
                           v.first_air_date, v.last_air_date, v.number_of_seasons,
                           v.number_of_episodes, v.vote_average, v.vote_count,
                           v.genres, v.origin_country, v.fetched_at,
                           c.popularity, c.adult
                    from admin.tv_card v
                    left join tmdb_catalog c on c.id = v.id
                    where {where}
                    order by {order}
                    limit %(limit)s offset %(offset)s
                ),
                -- La couverture par langue de la page, dans la même requête :
                -- une vignette porte ses pastilles de langue sans aller-retour
                -- supplémentaire.
                by_lang as (
                    select split_part(r.source_id, '/', 1) as sid,
                           r.lang,
                           count(distinct r.source_id)
                               filter (where r.http_status between 200 and 299) as ok,
                           count(distinct r.source_id)
                               filter (where r.http_status not between 200 and 299) as failed
                    from raw_source r
                    where r.source = %(source)s and r.kind = %(part_kind)s
                      and r.lang is not null
                      and split_part(r.source_id, '/', 1) = any (array(select id::text from page))
                    group by 1, 2
                ),
                langs as (
                    select sid,
                           jsonb_object_agg(lang, jsonb_build_object('ok', ok, 'failed', failed))
                               as coverage
                    from by_lang group by sid
                ),
                parts as (
                    select split_part(s.source_id, '/', 1) as sid, count(*) as expected
                    from fetch_state s
                    where s.source = %(source)s and s.kind = %(part_kind)s
                      and split_part(s.source_id, '/', 1) = any (array(select id::text from page))
                    group by 1
                )
                select p.*,
                       coalesce(l.coverage, '{{}}'::jsonb) as coverage,
                       coalesce(t.expected, 0) as parts_expected
                from page p
                left join langs l on l.sid = p.id::text
                left join parts t on t.sid = p.id::text
                order by {order_page}
                """
            ).format(
                where=where,
                order=order,
                order_page=sql.SQL("{} {} nulls last, p.id desc").format(
                    _page_column(q.sort), direction
                ),
            ),
            params,
        )
        rows = await cur.fetchall()

    return [_shape_card(row, q.lang) for row in rows], total


def _page_column(sort: str) -> sql.SQL:
    """Le SELECT final trie sur `page`, où les colonnes ont perdu leur préfixe."""
    return {
        "air_date": sql.SQL("p.first_air_date"),
        "name": sql.SQL("coalesce(p.name, p.original_name)"),
        "popularity": sql.SQL("p.popularity"),
        "fetched": sql.SQL("p.fetched_at"),
    }[sort]


def _shape_card(row: dict[str, Any], lang: str) -> dict[str, Any]:
    coverage: dict[str, Any] = row["coverage"] or {}
    expected = int(row["parts_expected"] or 0)
    selected = coverage.get(lang) or {"ok": 0, "failed": 0}
    ok = int(selected.get("ok") or 0)

    return {
        "id": row["id"],
        "name": row["name"] or row["original_name"],
        "originalName": row["original_name"],
        "overview": row["overview"],
        "posterPath": row["poster_path"],
        "backdropPath": row["backdrop_path"],
        "status": row["status"],
        "originalLanguage": row["original_language"],
        "firstAirDate": row["first_air_date"],
        "lastAirDate": row["last_air_date"],
        "year": row["first_air_date"].year if row["first_air_date"] else None,
        "seasons": row["number_of_seasons"],
        "episodes": row["number_of_episodes"],
        "voteAverage": row["vote_average"],
        "voteCount": row["vote_count"],
        "genres": [genre.get("name") for genre in (row["genres"] or []) if genre.get("name")],
        "originCountry": row["origin_country"] or [],
        "popularity": float(row["popularity"]) if row["popularity"] is not None else None,
        "fetchedAt": row["fetched_at"],
        "expectedParts": expected,
        "coverage": {
            code: {"ok": int(value.get("ok") or 0), "failed": int(value.get("failed") or 0)}
            for code, value in coverage.items()
        },
        "selected": {
            "lang": lang,
            "ok": ok,
            "failed": int(selected.get("failed") or 0),
            "ratio": (ok / expected) if expected else None,
        },
    }


async def fetch_work(
    conn: psycopg.AsyncConnection, work_id: int, lang: str
) -> dict[str, Any] | None:
    """La fiche complète, lue dans le brut.

    Les tableaux volumineux — visuels, distribution — sont tronqués **en SQL**
    par `jsonb_path_query_array` : on ne transporte pas six cents affiches pour
    en afficher dix-huit.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select r.fetched_at, r.http_status,
                   r.payload ->> 'name'                  as name,
                   r.payload ->> 'original_name'         as original_name,
                   r.payload ->> 'overview'              as overview,
                   r.payload ->> 'tagline'               as tagline,
                   r.payload ->> 'poster_path'           as poster_path,
                   r.payload ->> 'backdrop_path'         as backdrop_path,
                   r.payload ->> 'homepage'              as homepage,
                   r.payload ->> 'status'                as status,
                   r.payload ->> 'type'                  as type,
                   r.payload ->> 'original_language'     as original_language,
                   nullif(r.payload ->> 'first_air_date', '')      as first_air_date,
                   nullif(r.payload ->> 'last_air_date', '')       as last_air_date,
                   nullif(r.payload ->> 'number_of_seasons', '')::int  as number_of_seasons,
                   nullif(r.payload ->> 'number_of_episodes', '')::int as number_of_episodes,
                   nullif(r.payload ->> 'vote_average', '')::real  as vote_average,
                   nullif(r.payload ->> 'vote_count', '')::int     as vote_count,
                   coalesce(r.payload -> 'genres', '[]'::jsonb)         as genres,
                   coalesce(r.payload -> 'networks', '[]'::jsonb)       as networks,
                   coalesce(r.payload -> 'created_by', '[]'::jsonb)     as created_by,
                   coalesce(r.payload -> 'origin_country', '[]'::jsonb) as origin_country,
                   coalesce(r.payload -> 'seasons', '[]'::jsonb)        as seasons,
                   coalesce(r.payload -> 'external_ids', '{}'::jsonb)   as external_ids,
                   jsonb_path_query_array(r.payload, %(backdrops)s::jsonpath) as backdrops,
                   jsonb_path_query_array(r.payload, %(posters)s::jsonpath)   as posters,
                   -- `aggregate_credits` consolide toute la série ; `credits` ne
                   -- donne que la saison 1. On prend le premier des deux.
                   coalesce(
                       nullif(
                           jsonb_path_query_array(r.payload, %(agg_cast)s::jsonpath),
                           '[]'::jsonb
                       ),
                       jsonb_path_query_array(r.payload, %(cast)s::jsonpath)
                   ) as members,
                   coalesce((
                       select jsonb_agg(distinct t ->> 'iso_639_1')
                       from jsonb_array_elements(
                           coalesce(r.payload -> 'translations' -> 'translations', '[]'::jsonb)
                       ) t
                   ), '[]'::jsonb) as translations
            from raw_source r
            where r.source = %(source)s and r.kind = %(kind)s and r.source_id = %(id)s
              and r.http_status between 200 and 299
            order by r.fetched_at desc
            limit 1
            """,
            {
                "source": SOURCE,
                "kind": KIND_SERIES,
                "id": str(work_id),
                "backdrops": f"$.images.backdrops[0 to {GALLERY_LIMIT - 1}]",
                "posters": f"$.images.posters[0 to {GALLERY_LIMIT - 1}]",
                "agg_cast": f"$.aggregate_credits.cast[0 to {CAST_LIMIT - 1}]",
                "cast": f"$.credits.cast[0 to {CAST_LIMIT - 1}]",
            },
        )
        head = await cur.fetchone()
        if head is None:
            return None

        # L'état de collecte de chaque saison, langue par langue : c'est ce qui
        # dit à l'accordéon quelles langues il peut proposer.
        await cur.execute(
            """
            select split_part(source_id, '/', 2) as season,
                   lang,
                   max(http_status) as http_status,
                   max(fetched_at) as fetched_at
            from raw_source
            where source = %(source)s and kind = %(part_kind)s
              and split_part(source_id, '/', 1) = %(id)s
              and lang is not null
            group by 1, 2
            """,
            {"source": SOURCE, "part_kind": KIND_SEASON, "id": str(work_id)},
        )
        collected = await cur.fetchall()

        await cur.execute(
            "select popularity, adult, exported_on from tmdb_catalog where id = %s", (work_id,)
        )
        catalog = await cur.fetchone()

    by_season: dict[int, dict[str, Any]] = {}
    for row in collected:
        number = int(row["season"].removeprefix("s")) if row["season"].startswith("s") else -1
        by_season.setdefault(number, {})[row["lang"]] = {
            "status": row["http_status"],
            "fetchedAt": row["fetched_at"],
        }

    seasons = [
        {
            "seasonNumber": season.get("season_number"),
            "name": season.get("name"),
            "overview": season.get("overview"),
            "airDate": season.get("air_date") or None,
            "episodeCount": season.get("episode_count"),
            "posterPath": season.get("poster_path"),
            "collected": by_season.get(season.get("season_number"), {}),
            "hasSelectedLang": lang in by_season.get(season.get("season_number"), {}),
        }
        for season in head["seasons"]
    ]

    return {
        "id": work_id,
        "name": head["name"] or head["original_name"],
        "originalName": head["original_name"],
        "tagline": head["tagline"] or None,
        "overview": head["overview"],
        "posterPath": head["poster_path"],
        "backdropPath": head["backdrop_path"],
        "homepage": head["homepage"] or None,
        "status": head["status"],
        "type": head["type"],
        "originalLanguage": head["original_language"],
        "firstAirDate": head["first_air_date"],
        "lastAirDate": head["last_air_date"],
        "numberOfSeasons": head["number_of_seasons"],
        "numberOfEpisodes": head["number_of_episodes"],
        "voteAverage": head["vote_average"],
        "voteCount": head["vote_count"],
        "genres": [genre.get("name") for genre in head["genres"] if genre.get("name")],
        "networks": [
            {"name": network.get("name"), "logoPath": network.get("logo_path")}
            for network in head["networks"]
        ],
        "createdBy": [person.get("name") for person in head["created_by"] if person.get("name")],
        "originCountry": head["origin_country"],
        "externalIds": head["external_ids"],
        "translations": sorted(head["translations"] or []),
        "gallery": {
            "backdrops": [image.get("file_path") for image in head["backdrops"]],
            "posters": [image.get("file_path") for image in head["posters"]],
        },
        "cast": [_shape_member(member) for member in head["members"]],
        "seasons": seasons,
        "raw": {"fetchedAt": head["fetched_at"], "httpStatus": head["http_status"]},
        "catalog": (
            {
                "popularity": float(catalog["popularity"]),
                "adult": catalog["adult"],
                "exportedOn": catalog["exported_on"],
            }
            if catalog
            else None
        ),
    }


def _shape_member(member: dict[str, Any]) -> dict[str, Any]:
    """`aggregate_credits` porte les rôles dans un tableau `roles` ; `credits`
    met le personnage à plat dans `character`. On aplatit les deux pareil."""
    roles = member.get("roles") or []
    character = member.get("character") or (roles[0].get("character") if roles else None)
    episodes = member.get("total_episode_count") or (
        roles[0].get("episode_count") if roles else None
    )
    return {
        "id": member.get("id"),
        "name": member.get("name"),
        "character": character,
        "profilePath": member.get("profile_path"),
        "episodeCount": episodes,
    }


async def fetch_season(
    conn: psycopg.AsyncConnection, work_id: int, season_number: int, lang: str
) -> dict[str, Any] | None:
    """Les épisodes d'une saison, dans la langue demandée.

    Chargée à l'ouverture du volet, pas avec la fiche : une série de huit
    saisons en porte deux cents, et personne ne les lit toutes.

    C'est la seule vue où la langue change vraiment le contenu affiché — les
    synopsis d'épisode n'existent que parce que la collecte a redemandé la
    saison entière dans cette langue.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select r.lang, r.fetched_at, r.http_status,
                   r.payload ->> 'name'      as name,
                   r.payload ->> 'overview'  as overview,
                   nullif(r.payload ->> 'air_date', '') as air_date,
                   r.payload ->> 'poster_path' as poster_path,
                   coalesce(r.payload -> 'episodes', '[]'::jsonb) as episodes
            from raw_source r
            where r.source = %(source)s and r.kind = %(part_kind)s
              and r.source_id = %(id)s and r.lang = %(lang)s
              and r.http_status between 200 and 299
            order by r.fetched_at desc
            limit 1
            """,
            {
                "source": SOURCE,
                "part_kind": KIND_SEASON,
                "id": f"{work_id}/s{season_number}",
                "lang": lang,
            },
        )
        row = await cur.fetchone()

    if row is None:
        return None

    return {
        "lang": row["lang"],
        "fetchedAt": row["fetched_at"],
        "name": row["name"],
        "overview": row["overview"],
        "airDate": row["air_date"],
        "posterPath": row["poster_path"],
        "episodes": [
            {
                "episodeNumber": episode.get("episode_number"),
                "name": episode.get("name"),
                "overview": episode.get("overview"),
                "airDate": episode.get("air_date") or None,
                "runtime": episode.get("runtime"),
                "stillPath": episode.get("still_path"),
                "voteAverage": episode.get("vote_average"),
            }
            for episode in row["episodes"]
        ],
    }


async def refresh_cards(conn: psycopg.AsyncConnection) -> int:
    """Recalcule la projection et renvoie le nombre de vignettes.

    `concurrently` : le rafraîchissement ne prend pas de verrou exclusif, donc
    la grille reste consultable pendant qu'il tourne. Il exige l'index unique
    posé par la migration, et refuse de s'exécuter sur une vue jamais peuplée —
    d'où le repli sur un rafraîchissement bloquant au tout premier appel.
    """
    try:
        await conn.execute("refresh materialized view concurrently admin.tv_card")
    except psycopg.errors.ObjectNotInPrerequisiteState:
        await conn.execute("refresh materialized view admin.tv_card")

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from admin.tv_card")
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def cards_state(conn: psycopg.AsyncConnection) -> dict[str, Any]:
    """De quoi dire au front si la projection est vide, en retard, ou à jour."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select count(*) as total, max(fetched_at) as last_at from admin.tv_card")
        projection = await cur.fetchone() or {}
        await cur.execute(
            """
            select count(*) as total
            from fetch_state
            where source = %(source)s and kind = %(kind)s and last_success_at is not null
            """,
            {"source": SOURCE, "kind": KIND_SERIES},
        )
        collected = await cur.fetchone() or {}

    total = int(projection.get("total") or 0)
    available = int(collected.get("total") or 0)
    return {
        "projected": total,
        "collected": available,
        # « en retard » = des séries ont été collectées depuis le dernier
        # rafraîchissement. C'est le seul cas où le bouton sert vraiment.
        "stale": available > total,
        "lastAt": projection.get("last_at"),
    }
