"""Écriture dans `raw_source`, `fetch_state` et `riche_source`.

`raw_source` est *append-only* et **exclusivement TMDB** : aucune fonction de ce
module ne fait d'UPDATE dessus, et l'enrichissement n'y écrit jamais. La seule
chose qu'on évite, c'est de réécrire un contenu strictement identique — d'où
l'empreinte.

`oeuvre` est le pivot d'identité : aucun identifiant universel n'existe dehors
— la moitié du Wikidata « séries » ignore TMDB, TVmaze ne porte jamais d'id
TMDB — donc on tient le nôtre, et chaque identifiant externe y est nullable.

`riche_source` porte l'enrichissement — ce que les sources tierces apportent —
attaché au pivot par `oeuvre_id`. Une ligne par (œuvre, source, langue),
remplacée à chaque passe. `id_tmdb` et `raw_source_id` y sont nullables : une
œuvre hors TMDB n'a ni l'un ni l'autre.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


def payload_digest(payload: Any) -> bytes:
    """Empreinte stable d'une réponse JSON.

    Sérialisation canonique (clés triées, séparateurs fixes) pour que deux
    réponses sémantiquement identiques donnent la même empreinte quel que soit
    l'ordre des clés renvoyé par le serveur.

    Limite connue : TMDB recalcule `popularity` quotidiennement, donc un
    rafraîchissement journalier produira presque toujours une empreinte
    différente même sans changement réel. C'est volontairement laissé tel quel —
    ignorer des champs ici reviendrait à interpréter le brut. Si le volume
    devient un problème, ça se traite au niveau de la politique de
    rafraîchissement, pas de l'empreinte.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).digest()


async def store_raw(
    conn: psycopg.AsyncConnection,
    *,
    source: str,
    kind: str,
    source_id: str,
    lang: str | None,
    http_status: int,
    payload: dict[str, Any] | None,
) -> bool:
    """Insère une réponse brute. Renvoie True si une ligne a été créée,
    False si ce contenu exact était déjà stocké."""
    digest = payload_digest(payload)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict do nothing
            returning id
            """,
            (
                source,
                kind,
                source_id,
                lang,
                http_status,
                Jsonb(payload) if payload is not None else None,
                digest,
            ),
        )
        return await cur.fetchone() is not None


async def mark_fetch(
    conn: psycopg.AsyncConnection,
    *,
    source: str,
    kind: str,
    source_id: str,
    http_status: int,
    changed: bool,
    error: str | None = None,
) -> None:
    """Enregistre le passage sur un objet — succès ou échec.

    C'est ce qui remplace les trois fichiers JSON de la V1 : `last_fetched_at`
    répond à « quand l'a-t-on regardé », `last_changed_at` à « quand a-t-il
    bougé ». La V1 ne savait répondre ni à l'une ni à l'autre.
    """
    success = 200 <= http_status < 300
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into fetch_state (source, kind, source_id, last_fetched_at,
                                     last_success_at, last_changed_at,
                                     attempts, last_status, last_error)
            values (%(source)s, %(kind)s, %(source_id)s, now(),
                    case when %(success)s then now() end,
                    case when %(changed)s then now() end,
                    1, %(status)s, %(error)s)
            on conflict (source, kind, source_id) do update set
                last_fetched_at = now(),
                last_success_at = case when %(success)s then now()
                                       else fetch_state.last_success_at end,
                last_changed_at = case when %(changed)s then now()
                                       else fetch_state.last_changed_at end,
                attempts        = fetch_state.attempts + 1,
                last_status     = %(status)s,
                last_error      = %(error)s
            """,
            {
                "source": source,
                "kind": kind,
                "source_id": source_id,
                "success": success,
                "changed": changed,
                "status": http_status,
                "error": error,
            },
        )


async def latest_fiche_ids(conn: psycopg.AsyncConnection, ids: list[int]) -> dict[int, int]:
    """id TMDB → id de la dernière fiche collectée dans `raw_source`.

    C'est la référence de `riche_source` : une série sans fiche n'est pas
    enrichissable — la collecte d'abord.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select distinct on (source_id) source_id::int, id
            from raw_source
            where source = 'tmdb' and kind = 'tv'
              and source_id = any(%s)
              and http_status between 200 and 299
            order by source_id, fetched_at desc
            """,
            ([str(i) for i in ids],),
        )
        return dict(await cur.fetchall())


async def ensure_oeuvres(
    conn: psycopg.AsyncConnection, ids: list[int], *, univers: str = "series"
) -> dict[int, int]:
    """id TMDB → id d'œuvre, en créant les œuvres manquantes.

    Le pivot est créé paresseusement, à l'enrichissement : inutile de fabriquer
    228 000 lignes d'avance pour un catalogue dont 64 % n'auront jamais une
    ligne de riche_source.
    """
    if not ids:
        return {}
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into oeuvre (univers, id_tmdb)
            select %s, unnest(%s::int[])
            on conflict do nothing
            """,
            (univers, ids),
        )
        await cur.execute(
            "select id_tmdb, id from oeuvre where univers = %s and id_tmdb = any(%s)",
            (univers, ids),
        )
        return dict(await cur.fetchall())


async def attach_identifiers(
    conn: psycopg.AsyncConnection,
    oeuvre_id: int,
    *,
    wikidata_qid: str | None = None,
    imdb_id: str | None = None,
    tvmaze_id: int | None = None,
) -> None:
    """Pose sur l'œuvre les identifiants externes appris en route.

    `coalesce` : on complète, on n'écrase pas. Et une violation d'unicité n'est
    pas une erreur de programme — c'est **une réconciliation à faire** : une
    autre œuvre (saisie hors TMDB, typiquement) revendique déjà ce QID ou cet id
    TVmaze. On la journalise au lieu de tuer la passe ; la fusion est un geste
    humain, pas un effet de bord d'enrichissement.
    """
    try:
        async with conn.transaction():
            await conn.execute(
                """
                update oeuvre set
                    wikidata_qid = coalesce(wikidata_qid, %s),
                    imdb_id      = coalesce(imdb_id, %s),
                    tvmaze_id    = coalesce(tvmaze_id, %s)
                where id = %s
                """,
                (wikidata_qid, imdb_id, tvmaze_id, oeuvre_id),
            )
    except psycopg.errors.UniqueViolation as exc:
        log.warning(
            "œuvre %s : identifiant déjà revendiqué par une autre œuvre — "
            "réconciliation à faire (%s)",
            oeuvre_id,
            exc.diag.constraint_name,
        )


async def upsert_riche_source(
    conn: psycopg.AsyncConnection,
    *,
    oeuvre_id: int,
    raw_source_id: int | None = None,
    tv_id: int | None = None,
    source: str,
    lang: str = "",
    source_id: str,
    url: str | None = None,
    content: str | None = None,
    media: list[dict[str, Any]] | None = None,
    facts: dict[str, Any] | None = None,
    resolved_by: str | None = None,
) -> None:
    """Enregistre ce qu'une source tierce apporte sur une œuvre.

    La clé porte l'œuvre (pivot, source, langue) : c'est elle qui attache entre
    elles les lignes d'une même série, TMDB ou pas. `raw_source_id` et `tv_id`
    sont nullables — une œuvre hors TMDB n'a ni fiche ni id TMDB. Après une
    re-collecte, le ré-enrichissement met `raw_source_id` à jour au lieu de
    dupliquer.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into riche_source (oeuvre_id, raw_source_id, id_tmdb, source, lang,
                                      source_id, url, content, media, facts,
                                      resolved_by, fetched_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            on conflict (oeuvre_id, source, lang) do update set
                raw_source_id = excluded.raw_source_id,
                id_tmdb       = excluded.id_tmdb,
                source_id     = excluded.source_id,
                url           = excluded.url,
                content       = excluded.content,
                media         = excluded.media,
                facts         = excluded.facts,
                resolved_by   = excluded.resolved_by,
                fetched_at    = now()
            """,
            (
                oeuvre_id,
                raw_source_id,
                tv_id,
                source,
                lang,
                source_id,
                url,
                content,
                Jsonb(media or []),
                Jsonb(facts or {}),
                resolved_by,
            ),
        )


async def latest_payload(
    conn: psycopg.AsyncConnection,
    *,
    source: str,
    kind: str,
    source_id: str,
    lang: str | None = None,
) -> dict[str, Any] | None:
    """Dernière version connue d'un objet — le point d'entrée de la dérivation."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select payload from raw_source
            where source = %s and kind = %s and source_id = %s
              and (%s::text is null or lang = %s)
              and http_status between 200 and 299
            order by fetched_at desc
            limit 1
            """,
            (source, kind, source_id, lang, lang),
        )
        row = await cur.fetchone()
    return row[0] if row else None
