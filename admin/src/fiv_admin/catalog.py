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

from fiv_admin.media import country_of

SOURCE = "tmdb"
KIND_SERIES = "tv"
KIND_SEASON = "tv_season"

# La note, pondérée par le nombre de votants.
#
# Trier sur `vote_average` brut donne un classement inutile : une série notée
# 10 par un seul votant passe devant une série notée 8,4 par vingt-deux mille.
# Ce n'est pas un cas rare — c'est le sommet de la liste, entièrement occupé par
# des séries que personne n'a vues.
#
# La correction est la moyenne bayésienne, celle qu'IMDb applique à son Top 250 :
# on ajoute à chaque série `m` votes fictifs à la note moyenne du catalogue.
# Une série à trois votes reste donc tirée vers la moyenne, et il faut du volume
# pour s'en écarter — ce qui est exactement ce qu'on veut dire par « bien notée ».
#
#     (note × votants + C × m) / (votants + m)
#
# `m = 50` : le seuil à partir duquel une note commence à vouloir dire quelque
# chose. `C = 6,5` : la moyenne observée sur TMDB, où les notes se serrent haut.
# Les deux sont des constantes assumées, pas des réglages — les rendre
# configurables donnerait un classement dont personne ne saurait plus la règle.
NOTE_VOTES_FICTIFS = sql.Literal(50)
NOTE_MOYENNE = sql.Literal(6.5)

_NOTE_PONDEREE = """(case
        when coalesce({t}.vote_count, 0) = 0 then null
        else ({t}.vote_average * {t}.vote_count + {c} * {m}) / ({t}.vote_count + {m})
    end)"""


def _note(table: str) -> sql.Composable:
    """La note pondérée, écrite sur l'alias de table demandé.

    Une série sans aucun vote vaut `null`, jamais la moyenne : elle n'est pas
    « moyennement notée », elle n'est pas notée. Le `nulls last` du tri la
    renvoie donc en fin de liste dans les deux sens, ce qui est la seule place
    honnête pour une absence de note.
    """
    return sql.SQL(_NOTE_PONDEREE).format(t=sql.SQL(table), c=NOTE_MOYENNE, m=NOTE_VOTES_FICTIFS)


# Tris de la grille. Liste fermée : la clé vient de la requête HTTP, jamais le
# nom de colonne.
CARD_SORTS: dict[str, sql.Composable] = {
    # Le défaut demandé : de la plus récente à la plus ancienne.
    "air_date": sql.SQL("v.first_air_date"),
    # L'année seule, et c'est le seul tri qui rende un second critère utile.
    # Sur le jour exact, deux séries ont rarement la même date : le critère de
    # départage n'a alors rien à départager, et paraît ne pas fonctionner. À
    # l'année, les égalités sont massives, et « les plus récentes, et à année
    # égale les plus populaires » devient un classement lisible.
    "air_year": sql.SQL("extract(year from v.first_air_date)"),
    "name": sql.SQL("coalesce(v.name, v.original_name)"),
    "popularity": sql.SQL("c.popularity"),
    "rating": _note("v"),
    "fetched": sql.SQL("v.fetched_at"),
}

# Combien de visuels et de comédiens la fiche rapporte. Le brut en contient
# souvent des centaines ; les envoyer tous ferait peser une modale plus lourd
# que toute la grille.
GALLERY_LIMIT = 18
CAST_LIMIT = 30


# Les colonnes du SELECT final, où `page` a perdu les préfixes de tables.
PAGE_SORTS: dict[str, sql.Composable] = {
    "air_date": sql.SQL("p.first_air_date"),
    "air_year": sql.SQL("extract(year from p.first_air_date)"),
    "name": sql.SQL("coalesce(p.name, p.original_name)"),
    "popularity": sql.SQL("p.popularity"),
    "rating": _note("p"),
    "fetched": sql.SQL("p.fetched_at"),
}


@dataclass(frozen=True, slots=True)
class CardQuery:
    lang: str
    search: str | None = None
    min_popularity: float | None = None
    sort: str = "air_date"
    descending: bool = True
    # Le critère de départage. « Les plus récentes, et à date égale les plus
    # populaires » : sans lui, tout un lot de séries sorties le même jour tombe
    # dans un ordre arbitraire, qui change d'une page à l'autre.
    sort2: str | None = None
    descending2: bool = True
    # N'afficher que ce qui a une affiche. Une vignette sans visuel n'est pas un
    # défaut de la grille : TMDB n'en a pas pour tout le monde, et le fond de
    # catalogue en est largement dépourvu.
    with_poster: bool = False
    # N'afficher que ce qui a un synopsis. C'est la matière de la notation :
    # une série sans texte ne servira à rien au lot 5, quelle que soit son
    # affiche.
    with_overview: bool = False
    page: int = 1
    page_size: int = 24

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def criteria(self) -> tuple[tuple[str, bool], ...]:
        """Les critères effectifs, du plus fort au plus faible.

        Un second critère identique au premier est écarté : il ne départagerait
        rien, et laisser passer `order by x desc, x asc` produirait une clause
        contradictoire dont Postgres ne dirait rien.
        """
        if self.sort2 and self.sort2 != self.sort:
            return ((self.sort, self.descending), (self.sort2, self.descending2))
        return ((self.sort, self.descending),)


# Les traductions de la langue demandée, ordonnées : la région demandée
# d'abord, les autres ensuite.
#
# Deux points appris des données réelles, et non de la documentation de TMDB.
#
# **Un champ vide veut dire « pas de version localisée ».** Sur *Game of
# Thrones*, `en-US`, `de-DE` et `fr-FR` ont un `name` vide alors que leur
# `overview` est rempli : le titre n'est simplement pas traduit dans ces
# langues.
#
# **Chaque champ se résout indépendamment.** Toujours sur cette série, le titre
# français vient de `fr-CA` (« Le trône de fer ») pendant que le synopsis vient
# de `fr-FR`. Prendre une seule entrée pour les deux ferait perdre l'un ou
# l'autre — d'où une liste rendue par le SQL, et le choix fait en Python, champ
# par champ.
_TRADUCTIONS_LANGUE = """
                       coalesce((
                           select jsonb_agg(
                               t -> 'data' order by (t ->> 'iso_3166_1' = %(region)s) desc
                           )
                           from jsonb_array_elements(
                               coalesce(
                                   r.payload -> 'translations' -> 'translations', '[]'::jsonb
                               )
                           ) t
                           where t ->> 'iso_639_1' = %(lang2)s
                       ), '[]'::jsonb)"""


def _premier_non_vide(traductions: list[dict[str, Any]] | None, champ: str) -> str | None:
    """La première valeur non vide de ce champ, dans l'ordre rendu par le SQL."""
    for entree in traductions or []:
        valeur = (entree.get(champ) or "").strip()
        if valeur:
            return valeur
    return None


# Les traductions des seules séries de la page affichée.
#
# C'est la seule entorse à la règle « aucune liste ne lit `payload` », et elle
# est bornée : au plus `pageSize` payloads ouverts, jamais le catalogue entier.
# L'alternative était de porter les traductions dans la projection — de l'ordre
# de deux cents mégaoctets, et une liste de langues figée dans une migration
# alors que le contrat de données rappelle qu'elle est un réglage.
_TRADUCTIONS = sql.SQL(
    """
                , traductions as (
                    select distinct on (r.source_id) r.source_id as sid,"""
    + _TRADUCTIONS_LANGUE
    + """ as data
                    from raw_source r
                    where r.source = %(source)s and r.kind = %(kind)s
                      and r.http_status between 200 and 299 and r.payload is not null
                      and r.source_id = any (array(select id::text from page))
                    order by r.source_id, r.fetched_at desc
                )
"""
)


def _order_by(
    criteria: tuple[tuple[str, bool], ...],
    columns: dict[str, sql.Composable],
    tiebreak: sql.SQL,
) -> sql.SQL:
    """La clause de tri, plus un départage final sur l'id.

    Le départage n'est pas cosmétique : sans lui, deux lignes que tous les
    critères déclarent égales peuvent changer de place entre deux pages, et la
    pagination fait alors apparaître deux fois la même série ou en saute une.
    """
    parts = [
        sql.SQL("{} {} nulls last").format(
            columns[key], sql.SQL("desc") if desc else sql.SQL("asc")
        )
        for key, desc in criteria
    ]
    parts.append(tiebreak)
    return sql.SQL(", ").join(parts)


async def fetch_cards(
    conn: psycopg.AsyncConnection, q: CardQuery
) -> tuple[list[dict[str, Any]], int]:
    """Une page de vignettes, et le total du filtre."""
    # Le français est déjà dans la projection : inutile de rouvrir vingt-quatre
    # payloads pour retrouver ce qu'on a sous la main. C'est aussi la langue par
    # défaut, donc le cas le plus fréquent — la page d'accueil reste aussi
    # rapide qu'avant.
    langue = q.lang.split("-")[0]
    traduire = langue != "fr"

    params: dict[str, Any] = {
        "source": SOURCE,
        "kind": KIND_SERIES,
        "part_kind": KIND_SEASON,
        "lang2": langue,
        "region": q.lang.rpartition("-")[2],
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
            # `nullif` parce que TMDB renvoie tantôt `null`, tantôt une chaîne
            # vide : les deux veulent dire « pas d'affiche », et n'en traiter
            # qu'un laisserait passer des vignettes trouées.
            sql.SQL("nullif(v.poster_path, '') is not null") if q.with_poster else sql.SQL("true"),
            # Même précaution que pour l'affiche, et elle sert plus souvent
            # encore : un `overview` non traduit revient en chaîne vide, pas en
            # `null`. Tester `is not null` seul ne filtrerait presque rien.
            sql.SQL("nullif(btrim(v.overview), '') is not null")
            if q.with_overview
            else sql.SQL("true"),
        ]
    )

    order = _order_by(q.criteria, CARD_SORTS, sql.SQL("v.id desc"))
    order_page = _order_by(q.criteria, PAGE_SORTS, sql.SQL("p.id desc"))

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
                {traductions}
                select p.*,
                       coalesce(l.coverage, '{{}}'::jsonb) as coverage,
                       coalesce(t.expected, 0) as parts_expected,
                       {traduction}
                from page p
                left join langs l on l.sid = p.id::text
                left join parts t on t.sid = p.id::text
                {jointure}
                order by {order_page}
                """
            ).format(
                where=where,
                order=order,
                order_page=order_page,
                traductions=_TRADUCTIONS if traduire else sql.SQL(""),
                traduction=(
                    sql.SQL("coalesce(x.data, '[]'::jsonb) as traduction")
                    if traduire
                    else sql.SQL("'[]'::jsonb as traduction")
                ),
                jointure=(
                    sql.SQL("left join traductions x on x.sid = p.id::text")
                    if traduire
                    else sql.SQL("")
                ),
            ),
            params,
        )
        rows = await cur.fetchall()

    return [_shape_card(row, q.lang) for row in rows], total


def _repli_titre(row: dict[str, Any], lang: str) -> str | None:
    """Le titre à montrer faute de traduction : l'original, sauf en français."""
    if lang.split("-")[0] == "fr":
        return row["name"] or row["original_name"]
    return row["original_name"] or row["name"]


def _shape_card(row: dict[str, Any], lang: str) -> dict[str, Any]:
    # Le texte traduit s'il existe, le français sinon. La vignette ne dit pas
    # lequel des deux elle montre : sur une grille de vingt-quatre cartes, la
    # mention serait du bruit — c'est la fiche qui l'annonce, à l'endroit où on
    # lit vraiment le texte.
    traduites = row.get("traduction")
    nom = _premier_non_vide(traduites, "name")
    synopsis = _premier_non_vide(traduites, "overview")

    coverage: dict[str, Any] = row["coverage"] or {}
    expected = int(row["parts_expected"] or 0)
    selected = coverage.get(lang) or {"ok": 0, "failed": 0}
    ok = int(selected.get("ok") or 0)

    return {
        "id": row["id"],
        # Quand le titre n'est pas traduit, TMDB affiche le titre **original**,
        # pas la version française : un `name` vide dans les traductions veut
        # dire « cette langue n'a pas de titre à elle ». Retomber sur le
        # français afficherait « Le Trône de fer » à un lecteur arabophone dont
        # la série s'appelle « Game of Thrones » partout ailleurs.
        #
        # Le français fait exception, et c'est le seul : la fiche ayant été
        # demandée en `fr-FR`, la racine du payload porte déjà son titre
        # d'affichage — traductions comprises.
        "name": nom or _repli_titre(row, lang),
        "originalName": row["original_name"],
        "overview": synopsis or row["overview"],
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
                   ), '[]'::jsonb) as translations,
                   -- Le titre et le synopsis dans la langue demandée.
                   --
                   -- La fiche n'est téléchargée qu'une fois, en `fr-FR` : sans
                   -- cette extraction, changer de langue ne changeait rien au
                   -- texte affiché. Les traductions sont pourtant là — c'est
                   -- `append_to_response=translations` qui les apporte — mais
                   -- personne ne les lisait.
                   --
                   -- L'ordre départage les variantes régionales d'une même
                   -- langue : `ar-SA` d'abord, puis n'importe quel `ar`. TMDB
                   -- en renvoie plusieurs (ar-AE, ar-SA…) et prendre la
                   -- première venue donnerait un résultat instable d'une
                   -- collecte à l'autre.
                  coalesce((
                           select jsonb_agg(
                               t -> 'data' order by (t ->> 'iso_3166_1' = %(region)s) desc
                           )
                           from jsonb_array_elements(
                               coalesce(
                                   r.payload -> 'translations' -> 'translations', '[]'::jsonb
                               )
                           ) t
                           where t ->> 'iso_639_1' = %(lang2)s
                       ), '[]'::jsonb) as traduction,
                   -- La disponibilité en streaming, pour le pays de la langue
                   -- choisie seulement. Le brut en porte une centaine ; les
                   -- envoyer tous ferait transiter un catalogue mondial pour
                   -- afficher trois logos.
                   coalesce(
                       r.payload -> 'watch/providers' -> 'results' -> %(country)s,
                       '{}'::jsonb
                   ) as providers,
                   -- Les pays où la série est disponible, pour pouvoir dire
                   -- « rien chez vous, mais disponible ailleurs » plutôt qu'un
                   -- vide qu'on prendrait pour une donnée manquante.
                   coalesce((
                       select jsonb_agg(pays order by pays)
                       from jsonb_object_keys(
                           coalesce(r.payload -> 'watch/providers' -> 'results', '{}'::jsonb)
                       ) as pays
                   ), '[]'::jsonb) as provider_countries
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
                "country": country_of(lang) or "",
                "lang2": lang.split("-")[0],
                "region": country_of(lang) or "",
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

    # Le texte traduit s'il existe, le français sinon — et l'on dit lequel.
    # Afficher un synopsis français en prétendant montrer l'arabe induirait en
    # erreur sur ce qui est réellement collecté, ce que ce tableau de bord a
    # précisément pour rôle de mesurer.
    # Le français ne passe pas par les traductions : la fiche ayant été demandée
    # à TMDB avec `language=fr-FR`, la racine du payload porte déjà le titre
    # d'affichage français, résolu par TMDB lui-même. Y rechercher nous-mêmes
    # ramènerait par exemple le `fr-CA` « Le trône de fer » là où la racine dit
    # « Le Trône de fer » — une régression silencieuse sur la langue par défaut.
    traduites = head["traduction"] if lang.split("-")[0] != "fr" else []
    nom = _premier_non_vide(traduites, "name")
    synopsis = _premier_non_vide(traduites, "overview")
    accroche = _premier_non_vide(traduites, "tagline")

    return {
        "id": work_id,
        # Faute de titre traduit, TMDB montre le titre original — pas la
        # version française. Le français fait exception : la fiche ayant été
        # demandée en `fr-FR`, la racine du payload porte déjà son titre.
        "name": nom or _repli_titre(head, lang),
        "originalName": head["original_name"],
        "tagline": accroche or head["tagline"] or None,
        "overview": synopsis or head["overview"],
        # Ce que la langue choisie a réellement apporté. Le front s'en sert pour
        # signaler un repli plutôt que de le laisser passer inaperçu.
        "translated": {
            "lang": lang,
            "name": nom is not None,
            "overview": synopsis is not None,
        },
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
        "watch": _shape_watch(head["providers"], head["provider_countries"], lang),
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


# Les rubriques de TMDB, dans l'ordre où elles intéressent : par abonnement
# d'abord, puis gratuit, puis à l'acte. `ads` est le gratuit financé par la
# publicité, que JustWatch distingue du gratuit tout court.
WATCH_KINDS: tuple[tuple[str, str], ...] = (
    ("flatrate", "Par abonnement"),
    ("free", "Gratuit"),
    ("ads", "Gratuit avec publicité"),
    ("rent", "En location"),
    ("buy", "À l'achat"),
)


def _shape_watch(providers: dict[str, Any], countries: list[str], lang: str) -> dict[str, Any]:
    """Où regarder la série, dans le pays de la langue choisie.

    La donnée vient de JustWatch via TMDB, et TMDB impose de citer la source —
    c'est fait dans le front, à côté des logos.
    """
    country = country_of(lang)
    return {
        "country": country,
        # Le lien JustWatch du pays : la page qui fait autorité, et le seul
        # endroit où l'on saura si l'offre a changé depuis la collecte.
        "link": providers.get("link"),
        "offers": [
            {
                "kind": kind,
                "label": label,
                "providers": [
                    {
                        "id": provider.get("provider_id"),
                        "name": provider.get("provider_name"),
                        "logoPath": provider.get("logo_path"),
                    }
                    for provider in sorted(
                        providers.get(kind) or [],
                        key=lambda p: p.get("display_priority") or 0,
                    )
                ],
            }
            for kind, label in WATCH_KINDS
            if providers.get(kind)
        ],
        # Sert à distinguer « aucune plateforme dans ce pays » de « aucune
        # donnée de disponibilité du tout ».
        "countries": countries or [],
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
    """De quoi dire au front si la projection est vide, en retard, ou à jour.

    Le point délicat est le sens de « en retard ». Il se mesurait contre
    `fetch_state`, et c'était faux : cette table dit ce que la collecte a
    *tenté et réussi*, pas ce qu'elle a *stocké*. Les deux peuvent diverger —
    observé en production, 226 séries marquées « succès HTTP 200 » sans aucune
    ligne dans `raw_source` — et le bandeau restait alors allumé pour toujours,
    puisqu'aucun rafraîchissement ne pouvait projeter des séries dont le brut
    n'existe pas.

    Le compte se fait donc contre **ce dont la projection est faite** : les
    identifiants distincts que la vue matérialisée retiendrait si on la
    recalculait maintenant. Par construction, l'égalité signifie « à jour », et
    aucune incohérence en amont ne peut plus allumer le bandeau à tort.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select count(*) as total, max(fetched_at) as last_at from admin.tv_card")
        projection = await cur.fetchone() or {}

        # Exactement le filtre de `002_admin_cards.sql`. Parcours d'index seul
        # grâce à `raw_source_latest_idx (source, kind, source_id, …)`, mais ce
        # `count(distinct)` reste le poste le plus cher de cette réponse : il
        # justifierait un cache si la page devenait lente.
        await cur.execute(
            """
            select count(distinct source_id) as total
            from raw_source
            where source = %(source)s and kind = %(kind)s
              and http_status between 200 and 299 and payload is not null
            """,
            {"source": SOURCE, "kind": KIND_SERIES},
        )
        projetables = await cur.fetchone() or {}

        # Gardé pour l'affichage, et parce que l'écart entre les deux est en soi
        # un signal : une collecte qui se dit réussie sans rien avoir stocké.
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
    disponibles = int(projetables.get("total") or 0)
    return {
        "projected": total,
        "collected": int(collected.get("total") or 0),
        "projectable": disponibles,
        # Ce qu'un rafraîchissement ajouterait — donc ce que le bouton sert à
        # faire, et rien d'autre.
        "pending": max(0, disponibles - total),
        "stale": disponibles > total,
        "lastAt": projection.get("last_at"),
    }
