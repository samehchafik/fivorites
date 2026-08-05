"""Ce qui a bougé chez TMDB depuis notre dernière collecte.

`/tv/changes` renvoie les ids modifiés sur une fenêtre donnée. On ne s'en sert
pas pour collecter directement : on note la date de modification dans le
catalogue, et `backfill` compare cette date à `fetch_state.last_success_at`.

Cette indirection est ce qui rend le mécanisme robuste. Une commande qui
collecterait immédiatement perdrait tout si elle échouait en cours de route ;
ici, la marque reste en base jusqu'à ce qu'une collecte réussisse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import psycopg

from fiv_sourcing.sources.tmdb.client import TmdbClient

log = logging.getLogger(__name__)

# TMDB refuse les fenêtres de plus de 14 jours. Au-delà, il faut découper —
# ou simplement admettre qu'un rattrapage complet passe par `--refresh-after`.
MAX_WINDOW_DAYS = 14

# Garde-fou : la pagination est bornée par `total_pages`, mais une réponse
# aberrante ne doit pas faire tourner la boucle indéfiniment.
MAX_PAGES = 500


@dataclass(slots=True)
class ChangesReport:
    start: date
    end: date
    pages: int = 0
    ids_seen: int = 0
    marked: int = 0
    unknown: int = 0  # signalées par TMDB mais absentes de notre catalogue
    truncated: bool = False


async def fetch_changed_ids(
    client: TmdbClient, start: date, end: date
) -> tuple[set[int], int, bool]:
    """Ids modifiés entre deux dates. Renvoie (ids, pages lues, tronqué)."""
    ids: set[int] = set()
    page = 1
    total_pages = 1

    while page <= total_pages and page <= MAX_PAGES:
        result = await client.changes(start.isoformat(), page=page, end_date=end.isoformat())
        if not result.ok or result.payload is None:
            log.warning("page %s de /tv/changes : %s", page, result.error or result.status)
            break

        for entry in result.payload.get("results") or []:
            if (identifier := entry.get("id")) is not None:
                ids.add(identifier)

        total_pages = int(result.payload.get("total_pages") or 1)
        page += 1

    return ids, page - 1, total_pages > MAX_PAGES


async def mark_changed(
    conn: psycopg.AsyncConnection, ids: set[int], at: datetime | None = None
) -> int:
    """Note la modification sur les séries connues. Renvoie le nombre marqué.

    Les ids inconnus sont ignorés volontairement : une série créée aujourd'hui
    apparaît dans `changes` avant d'entrer dans l'export quotidien. L'insérer
    ici avec des colonnes vides mélangerait deux sources ; l'export la
    rattrapera demain, et `backfill` la prendra comme n'importe quelle nouveauté.
    """
    if not ids:
        return 0

    moment = at or datetime.now(UTC)
    async with conn.cursor() as cur:
        await cur.execute(
            "update tmdb_catalog set changed_at = %s where id = any(%s)",
            (moment, list(ids)),
        )
        return cur.rowcount


async def refresh_changes(
    conn: psycopg.AsyncConnection,
    client: TmdbClient,
    *,
    days: int = 1,
    today: date | None = None,
) -> ChangesReport:
    end = today or date.today()
    start = end - timedelta(days=min(days, MAX_WINDOW_DAYS))

    report = ChangesReport(start=start, end=end)
    ids, report.pages, report.truncated = await fetch_changed_ids(client, start, end)
    report.ids_seen = len(ids)
    report.marked = await mark_changed(conn, ids)
    report.unknown = report.ids_seen - report.marked
    return report
