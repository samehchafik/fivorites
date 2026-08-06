"""Les lectures du tableau d'acquisition.

Tout part de trois tables de `sourcing` et d'une règle de nommage :

    fiche    `raw_source.source_id = '1399'`      `fetch_state` idem
    saison   `raw_source.source_id = '1399/s2'`   une ligne **par langue**

L'id de la série est donc le préfixe de `source_id`, d'où les
`split_part(source_id, '/', 1)` qui reviennent partout — indexés par
`001_admin.sql`.

Deux principes de coût, parce que le catalogue fait 228 000 séries et que le
brut en fera plusieurs millions de lignes :

1. **On ne touche jamais à `payload` dans le tableau.** Un payload de fiche
   pèse des centaines de kilooctets ; en lire cinquante pour afficher une page
   coûterait plus cher que tout le reste réuni. Le nombre de saisons attendues
   se lit dans `fetch_state`, qui porte une ligne par saison énumérée, succès
   ou échec. Le payload n'est ouvert que pour le détail d'une série, une ligne
   à la fois.
2. **On pagine avant d'agréger.** Les jointures ne portent jamais sur le
   catalogue entier mais sur les identifiants de la page courante.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fiv_admin.media import Media

SOURCE = "tmdb"

# Tris proposés. Liste fermée : le nom de colonne ne vient jamais de la requête
# HTTP, seulement d'une clé qui s'y trouve.
SORTS: dict[str, sql.SQL] = {
    "popularity": sql.SQL("c.popularity"),
    "id": sql.SQL("c.id"),
    "name": sql.SQL("c.original_name"),
    # Le tri par fraîcheur impose une jointure interne sur `fetch_state` : il ne
    # peut lister que les œuvres déjà regardées. C'est dit dans le front.
    "fetched": sql.SQL("f.last_fetched_at"),
}

STATUSES = (
    "all",  # tout le catalogue
    "absent",  # jamais regardé
    "collected",  # fiche récupérée avec succès
    "error",  # dernier passage en erreur
    "lang_ok",  # au moins une partie collectée dans la langue choisie
    "lang_missing",  # fiche connue, rien dans la langue choisie
)


@dataclass(frozen=True, slots=True)
class ItemsQuery:
    media: Media
    lang: str
    status: str = "all"
    search: str | None = None
    min_popularity: float | None = None
    sort: str = "popularity"
    descending: bool = True
    page: int = 1
    page_size: int = 50

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


async def fetch_items(
    conn: psycopg.AsyncConnection, q: ItemsQuery
) -> tuple[list[dict[str, Any]], int]:
    """Une page du tableau, et le nombre total de lignes du filtre."""
    catalog = sql.Identifier(q.media.catalog_table or "")
    order = sql.SQL("{} {} nulls last").format(
        SORTS[q.sort], sql.SQL("desc") if q.descending else sql.SQL("asc")
    )

    # Le tri par fraîcheur a besoin de `fetch_state` dès la sélection ; les
    # autres n'en veulent pas, pour rester sur un seul index du catalogue.
    join = (
        sql.SQL(
            """
            join fetch_state f
              on f.source = %(source)s and f.kind = %(kind)s and f.source_id = c.id::text
            """
        )
        if q.sort == "fetched"
        else sql.SQL("")
    )

    params: dict[str, Any] = {
        "source": SOURCE,
        "kind": q.media.kind,
        "part_kind": q.media.part_kind,
        "lang": q.lang,
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
                " or c.original_name ilike %(like)s"
                " or c.id = %(search_id)s::int)"
            ),
            sql.SQL("(%(min_popularity)s::real is null or c.popularity >= %(min_popularity)s)"),
            _status_predicate(q.status),
        ]
    )

    count_sql = sql.SQL("select count(*) as total from {catalog} c {join} where {where}").format(
        catalog=catalog, join=join, where=where
    )

    page_sql = sql.SQL(
        """
        with page as (
            select c.id, c.original_name, c.popularity, c.adult,
                   c.exported_on, c.first_seen_at, c.last_seen_at
            from {catalog} c
            {join}
            where {where}
            order by {order}, c.id
            limit %(limit)s offset %(offset)s
        ),
        -- L'état de la fiche : ce que la collecte a retenu de son dernier
        -- passage. Aucune lecture de payload.
        --
        -- `= any (array(...))` plutôt que `in (...)` : la première forme donne
        -- un parcours d'index par valeur, la seconde laisse le planificateur
        -- choisir une jointure de hachage — sur une table de plusieurs millions
        -- de lignes, la différence est celle d'un balayage complet.
        fiche as (
            select s.source_id as sid, s.last_fetched_at, s.last_success_at,
                   s.last_changed_at, s.last_status, s.last_error, s.attempts
            from fetch_state s
            where s.source = %(source)s and s.kind = %(kind)s
              and s.source_id = any (array(select id::text from page))
        ),

        -- Le dénominateur de la couverture : une ligne de `fetch_state` par
        -- partie énumérée depuis la fiche, qu'elle ait abouti ou non.
        parts as (
            select split_part(s.source_id, '/', 1) as sid,
                   count(*) as expected,
                   max(s.last_fetched_at) as last_at
            from fetch_state s
            where s.source = %(source)s and s.kind = %(part_kind)s
              and split_part(s.source_id, '/', 1) = any (array(select id::text from page))
            group by 1
        ),

        -- Le numérateur, langue par langue. `count(distinct source_id)` parce
        -- qu'une même saison peut avoir plusieurs versions horodatées dans le
        -- brut : ce qu'on compte, ce sont les saisons couvertes, pas les
        -- téléchargements.
        by_lang as (
            select split_part(r.source_id, '/', 1) as sid,
                   r.lang,
                   count(distinct r.source_id)
                       filter (where r.http_status between 200 and 299) as ok,
                   count(distinct r.source_id)
                       filter (where r.http_status not between 200 and 299) as failed,
                   max(r.fetched_at) as last_at
            from raw_source r
            where r.source = %(source)s and r.kind = %(part_kind)s
              and r.lang is not null
              and split_part(r.source_id, '/', 1) = any (array(select id::text from page))
            group by 1, 2
        ),
        langs as (
            select sid,
                   jsonb_object_agg(
                       lang,
                       jsonb_build_object('ok', ok, 'failed', failed, 'lastAt', last_at)
                   ) as coverage
            from by_lang
            group by sid
        )

        select p.id, p.original_name, p.popularity, p.adult, p.exported_on,
               f.last_fetched_at, f.last_success_at, f.last_changed_at,
               f.last_status, f.last_error, f.attempts,
               coalesce(t.expected, 0) as parts_expected,
               t.last_at as parts_last_at,
               coalesce(l.coverage, '{{}}'::jsonb) as coverage
        from page p
        left join fiche  f on f.sid = p.id::text
        left join parts  t on t.sid = p.id::text
        left join langs  l on l.sid = p.id::text
        order by {order_page}, p.id
        """
    ).format(
        catalog=catalog,
        join=join,
        where=where,
        order=order,
        # Dans le SELECT final les colonnes viennent de `page`, pas de `c`.
        order_page=sql.SQL("{} {} nulls last").format(
            sql.SQL("p.popularity")
            if q.sort == "popularity"
            else sql.SQL("p.id")
            if q.sort == "id"
            else sql.SQL("p.original_name")
            if q.sort == "name"
            else sql.SQL("f.last_fetched_at"),
            sql.SQL("desc") if q.descending else sql.SQL("asc"),
        ),
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(count_sql, params)
        row = await cur.fetchone()
        total = int(row["total"]) if row else 0

        await cur.execute(page_sql, params)
        rows = await cur.fetchall()

    return [_shape_item(row, q.lang) for row in rows], total


def _status_predicate(status: str) -> sql.SQL:
    fiche = (
        "select 1 from fetch_state s"
        " where s.source = %(source)s and s.kind = %(kind)s and s.source_id = c.id::text"
    )
    part_ok = (
        "select 1 from raw_source r"
        " where r.source = %(source)s and r.kind = %(part_kind)s and r.lang = %(lang)s"
        "   and split_part(r.source_id, '/', 1) = c.id::text"
        "   and r.http_status between 200 and 299"
    )
    match status:
        case "absent":
            return sql.SQL(f"not exists ({fiche})")
        case "collected":
            return sql.SQL(f"exists ({fiche} and s.last_success_at is not null)")
        case "error":
            return sql.SQL(
                f"exists ({fiche} and (s.last_status >= 400 or s.last_error is not null))"
            )
        case "lang_ok":
            return sql.SQL(f"exists ({part_ok})")
        case "lang_missing":
            return sql.SQL(
                f"exists ({fiche} and s.last_success_at is not null) and not exists ({part_ok})"
            )
        case _:
            return sql.SQL("true")


def _shape_item(row: dict[str, Any], lang: str) -> dict[str, Any]:
    coverage: dict[str, Any] = row["coverage"] or {}
    expected = int(row["parts_expected"] or 0)
    selected = coverage.get(lang) or {"ok": 0, "failed": 0, "lastAt": None}

    return {
        "id": row["id"],
        "title": row["original_name"],
        "popularity": float(row["popularity"] or 0),
        "adult": row["adult"],
        "exportedOn": row["exported_on"],
        "expectedParts": expected,
        "coverage": {
            code: {
                "ok": int(value.get("ok") or 0),
                "failed": int(value.get("failed") or 0),
                "lastAt": value.get("lastAt"),
            }
            for code, value in coverage.items()
        },
        "selected": {
            "lang": lang,
            "ok": int(selected.get("ok") or 0),
            "failed": int(selected.get("failed") or 0),
            "lastAt": selected.get("lastAt"),
            "ratio": (int(selected.get("ok") or 0) / expected) if expected else None,
        },
        "fetch": {
            "lastFetchedAt": row["last_fetched_at"],
            "lastSuccessAt": row["last_success_at"],
            "lastChangedAt": row["last_changed_at"],
            "lastStatus": row["last_status"],
            "lastError": row["last_error"],
            "attempts": row["attempts"] or 0,
            "partsLastAt": row["parts_last_at"],
        },
        "state": _state(row, selected, expected),
    }


def _state(row: dict[str, Any], selected: dict[str, Any], expected: int) -> str:
    """L'état d'une œuvre **dans la langue choisie**.

    Six valeurs, dans l'ordre où elles se lisent : jamais regardée, en échec,
    fiche seule, rien dans cette langue, partiellement couverte, complète.
    """
    if row["last_fetched_at"] is None:
        return "absent"
    if row["last_success_at"] is None:
        return "error"
    ok = int(selected.get("ok") or 0)
    if expected == 0:
        return "series_only"
    if ok == 0:
        return "lang_missing"
    return "complete" if ok >= expected else "partial"


async def fetch_detail(
    conn: psycopg.AsyncConnection, media: Media, work_id: int
) -> dict[str, Any] | None:
    """Le détail d'une œuvre : l'inventaire, l'état, et la matrice
    langue × partie.

    C'est le seul endroit où on ouvre un `payload`, et pour une seule ligne :
    le titre traduit et la liste des traductions déclarées par TMDB ne se
    trouvent nulle part ailleurs.
    """
    catalog = sql.Identifier(media.catalog_table or "")
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql.SQL(
                """
                select c.id, c.original_name, c.popularity, c.adult, c.exported_on,
                       c.first_seen_at, c.last_seen_at,
                       s.last_fetched_at, s.last_success_at, s.last_changed_at,
                       s.last_status, s.last_error, s.attempts, s.priority
                from {catalog} c
                left join fetch_state s
                  on s.source = %(source)s and s.kind = %(kind)s and s.source_id = c.id::text
                where c.id = %(id)s
                """
            ).format(catalog=catalog),
            {"source": SOURCE, "kind": media.kind, "id": work_id},
        )
        head = await cur.fetchone()
        if head is None:
            return None

        # Le brut de la fiche : la dernière version, et rien que les champs
        # utiles à l'affichage — le payload complet pèse trop pour transiter.
        await cur.execute(
            """
            select r.fetched_at, r.http_status,
                   r.payload ->> 'name'            as name,
                   r.payload ->> 'first_air_date'  as first_air_date,
                   r.payload ->> 'status'          as tmdb_status,
                   r.payload ->> 'original_language' as original_language,
                   r.payload -> 'origin_country'   as origin_country,
                   jsonb_array_length(coalesce(r.payload -> 'seasons', '[]'::jsonb))
                                                   as seasons_declared,
                   coalesce((
                       select jsonb_agg(distinct t ->> 'iso_639_1')
                       from jsonb_array_elements(
                           coalesce(r.payload -> 'translations' -> 'translations', '[]'::jsonb)
                       ) t
                   ), '[]'::jsonb)                  as translations
            from raw_source r
            where r.source = %(source)s and r.kind = %(kind)s and r.source_id = %(id)s
              and r.http_status between 200 and 299
            order by r.fetched_at desc
            limit 1
            """,
            {"source": SOURCE, "kind": media.kind, "id": str(work_id)},
        )
        payload = await cur.fetchone()

        parts: list[dict[str, Any]] = []
        if media.part_kind:
            await cur.execute(
                """
                select r.source_id, r.lang, r.http_status, r.fetched_at
                from (
                    select distinct on (source_id, lang)
                           source_id, lang, http_status, fetched_at
                    from raw_source
                    where source = %(source)s and kind = %(part_kind)s
                      and split_part(source_id, '/', 1) = %(id)s
                    order by source_id, lang, fetched_at desc
                ) r
                order by r.source_id, r.lang
                """,
                {"source": SOURCE, "part_kind": media.part_kind, "id": str(work_id)},
            )
            parts = list(await cur.fetchall())

    matrix: dict[str, dict[str, Any]] = {}
    for row in parts:
        entry = matrix.setdefault(row["source_id"], {})
        entry[row["lang"]] = {
            "status": row["http_status"],
            "fetchedAt": row["fetched_at"],
        }

    return {
        "id": head["id"],
        "title": head["original_name"],
        "popularity": float(head["popularity"] or 0),
        "adult": head["adult"],
        "exportedOn": head["exported_on"],
        "firstSeenAt": head["first_seen_at"],
        "lastSeenAt": head["last_seen_at"],
        "fetch": {
            "lastFetchedAt": head["last_fetched_at"],
            "lastSuccessAt": head["last_success_at"],
            "lastChangedAt": head["last_changed_at"],
            "lastStatus": head["last_status"],
            "lastError": head["last_error"],
            "attempts": head["attempts"] or 0,
            "priority": head["priority"],
        },
        "payload": (
            {
                "fetchedAt": payload["fetched_at"],
                "httpStatus": payload["http_status"],
                "name": payload["name"],
                "firstAirDate": payload["first_air_date"],
                "tmdbStatus": payload["tmdb_status"],
                "originalLanguage": payload["original_language"],
                "originCountry": payload["origin_country"] or [],
                "seasonsDeclared": payload["seasons_declared"],
                "translations": payload["translations"] or [],
            }
            if payload
            else None
        ),
        "parts": [
            {"id": part_id, "langs": langs}
            for part_id, langs in sorted(matrix.items(), key=_part_key)
        ],
    }


def _part_key(item: tuple[str, Any]) -> tuple[int, str]:
    """Trie `1399/s2` avant `1399/s10` — un tri texte les mettrait à l'envers."""
    tail = item[0].rsplit("/s", 1)[-1]
    return (int(tail), item[0]) if tail.isdigit() else (10**9, item[0])


async def fetch_summary(conn: psycopg.AsyncConnection, media: Media) -> dict[str, Any]:
    """Les compteurs d'en-tête : le catalogue, l'avancement des fiches,
    la couverture par langue, et les dernières erreurs.

    Requête lourde par nature — elle balaie `raw_source` pour compter les
    langues. Le cache d'appel s'en charge (voir `SummaryCache`).
    """
    catalog = sql.Identifier(media.catalog_table or "")
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql.SQL(
                """
                select count(*) as total,
                       max(exported_on) as exported_on,
                       count(*) filter (where popularity >= 1) as popular
                from {catalog}
                """
            ).format(catalog=catalog)
        )
        catalog_row = await cur.fetchone() or {}

        await cur.execute(
            """
            select count(*) as seen,
                   count(*) filter (where last_success_at is not null) as ok,
                   count(*) filter (where last_status >= 400) as failed,
                   -- Le débit de la dernière heure. C'est ce qui transforme
                   -- « il en reste 216 000 » en « il en reste pour deux jours »,
                   -- seule forme sous laquelle le chiffre aide à décider.
                   count(*) filter (where last_fetched_at > now() - interval '1 hour')
                       as last_hour,
                   max(last_fetched_at) as last_at
            from fetch_state
            where source = %(source)s and kind = %(kind)s
            """,
            {"source": SOURCE, "kind": media.kind},
        )
        works = await cur.fetchone() or {}

        parts = {"expected": 0, "last_at": None}
        by_lang: list[dict[str, Any]] = []
        if media.part_kind:
            await cur.execute(
                """
                select count(*) as expected, max(last_fetched_at) as last_at
                from fetch_state
                where source = %(source)s and kind = %(part_kind)s
                """,
                {"source": SOURCE, "part_kind": media.part_kind},
            )
            parts = await cur.fetchone() or parts

            await cur.execute(
                """
                select r.lang,
                       count(*) as rows_total,
                       count(distinct r.source_id)
                           filter (where r.http_status between 200 and 299) as parts_ok,
                       count(distinct split_part(r.source_id, '/', 1))
                           filter (where r.http_status between 200 and 299) as works_ok,
                       count(*) filter (where r.http_status not between 200 and 299) as failed,
                       max(r.fetched_at) as last_at
                from raw_source r
                where r.source = %(source)s and r.kind = %(part_kind)s and r.lang is not null
                group by r.lang
                """,
                {"source": SOURCE, "part_kind": media.part_kind},
            )
            by_lang = list(await cur.fetchall())

        await cur.execute(
            """
            select kind, source_id, last_status, last_error, last_fetched_at
            from fetch_state
            where source = %(source)s and last_error is not null
              and kind = any(%(kinds)s::text[])
            order by last_fetched_at desc
            limit 10
            """,
            {
                "source": SOURCE,
                "kinds": [k for k in (media.kind, media.part_kind) if k],
            },
        )
        errors = list(await cur.fetchall())

    return {
        "catalog": {
            "total": int(catalog_row.get("total") or 0),
            "popular": int(catalog_row.get("popular") or 0),
            "exportedOn": catalog_row.get("exported_on"),
        },
        "works": {
            "seen": int(works.get("seen") or 0),
            "ok": int(works.get("ok") or 0),
            "failed": int(works.get("failed") or 0),
            # Ce qui n'a jamais été regardé. Calculé plutôt que compté : une
            # anti-jointure sur 228 000 lignes pour un chiffre qu'une
            # soustraction donne exactement.
            "remaining": max(0, int(catalog_row.get("total") or 0) - int(works.get("seen") or 0)),
            "lastHour": int(works.get("last_hour") or 0),
            "lastAt": works.get("last_at"),
        },
        "parts": {
            "expected": int(parts.get("expected") or 0),
            "lastAt": parts.get("last_at"),
        },
        "byLang": {
            row["lang"]: {
                "rows": int(row["rows_total"] or 0),
                "partsOk": int(row["parts_ok"] or 0),
                "worksOk": int(row["works_ok"] or 0),
                "failed": int(row["failed"] or 0),
                "lastAt": row["last_at"],
            }
            for row in by_lang
        },
        "errors": [
            {
                "kind": row["kind"],
                "sourceId": row["source_id"],
                "status": row["last_status"],
                "error": row["last_error"],
                "at": row["last_fetched_at"],
            }
            for row in errors
        ],
    }


class SummaryCache:
    """Mémorise les compteurs d'en-tête quelques secondes.

    Ils agrègent le brut en entier : les recalculer à chaque affichage
    reviendrait à faire payer un balayage complet à chaque changement de page.
    Une minute de retard sur un chiffre d'avancement n'a aucune conséquence.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > self._ttl:
            self._entries.pop(key, None)
            return None
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._entries[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._entries.clear()


async def observed_languages(conn: psycopg.AsyncConnection, media: Media) -> list[str]:
    """Langues réellement présentes dans le brut pour cet univers.

    Passe par `fetch_state`… non : la langue n'y est pas (une saison y a une
    seule ligne, toutes langues confondues). C'est donc `raw_source` qu'on
    interroge, mais uniquement sur l'index `(source, kind, lang)` —
    `group by` plutôt que `distinct` pour rester en parcours d'index.
    """
    if not media.part_kind:
        return []
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select lang from raw_source
            where source = %(source)s and kind = %(part_kind)s and lang is not null
            group by lang order by lang
            """,
            {"source": SOURCE, "part_kind": media.part_kind},
        )
        return [row[0] for row in await cur.fetchall()]
