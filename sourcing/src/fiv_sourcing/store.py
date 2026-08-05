"""Écriture dans `raw_source` et `fetch_state`.

`raw_source` est *append-only* : aucune fonction de ce module ne fait d'UPDATE
dessus. La seule chose qu'on évite, c'est de réécrire un contenu strictement
identique — d'où l'empreinte.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


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
