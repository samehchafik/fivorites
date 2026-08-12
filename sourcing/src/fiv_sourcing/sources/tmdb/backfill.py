"""Collecte de masse : tout le catalogue, sans filtre ni arbitrage.

Aucune sélection éditoriale ici. La couche d'acquisition prend tout ce que TMDB
expose ; ce qui mérite d'être montré est une question de produit, tranchée en
aval sur des données complètes plutôt qu'en amont sur une intuition.

En particulier, `popularity` n'est jamais un critère de rétention : c'est une
mesure de l'attention des utilisateurs *de TMDB*, dont la base est très
majoritairement occidentale. S'en servir pour filtrer écarterait
systématiquement les catalogues arabe et turc — mesuré : un seuil à 5 ne
retiendrait que 54 des 5 560 séries en écriture arabe.

Une seule connexion suffit malgré la concurrence : `cursor.execute` prend le
verrou de la connexion, donc les écritures se sérialisent. Au débit où l'on
tourne, l'écriture n'est jamais le facteur limitant — le réseau l'est.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from fiv_sourcing.sources.tmdb.client import TmdbClient
from fiv_sourcing.sources.tmdb.collect import collect_series

log = logging.getLogger(__name__)

ORDERS = {
    # Neutre : aucun jugement implicite sur ce qui compte. C'est le défaut.
    #
    # Attention pour autant : les petits ids sont les plus anciennes entrées de
    # TMDB, donc les séries installées à nombreuses saisons. Un `--limit 200`
    # dans cet ordre coûte bien plus de requêtes par série que la moyenne du
    # catalogue — c'est un mauvais échantillon pour estimer une durée.
    "id": "c.id",
    # Pour estimer : seul ordre dont la moyenne vaut celle du catalogue.
    "random": "random()",
    # Utile si la passe risque d'être interrompue : les plus consultées
    # d'abord. À n'employer qu'en connaissance de ce que `popularity` mesure.
    "popularity": "c.popularity desc, c.id",
}


@dataclass(slots=True)
class BackfillReport:
    selected: int = 0
    done: int = 0
    ok: int = 0
    failed: int = 0
    requests: int = 0
    rows_written: int = 0
    interrupted: bool = False

    @property
    def remaining(self) -> int:
        return self.selected - self.done


async def pending_ids(
    conn: psycopg.AsyncConnection,
    *,
    refresh_after: int | None = None,
    limit: int | None = None,
    order: str = "id",
) -> list[int]:
    """Séries à collecter, pour trois raisons distinctes.

    1. **jamais collectées** — nouveautés apportées par l'export quotidien ;
    2. **signalées modifiées** par `/tv/changes` depuis notre dernière réussite ;
    3. **trop anciennes**, si `refresh_after` est donné.

    La deuxième est ce qui rend l'entretien peu coûteux : au lieu de tout
    recollecter périodiquement, on ne reprend que ce que TMDB dit avoir bougé.
    """
    if order not in ORDERS:
        raise ValueError(f"tri inconnu : {order} (attendu : {', '.join(ORDERS)})")

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            select c.id
            from tmdb_catalog c
            left join fetch_state f
                   on f.source = 'tmdb' and f.kind = 'tv' and f.source_id = c.id::text
            where c.univers = 'series'
              and (f.last_success_at is null
                   or (c.changed_at is not null and c.changed_at > f.last_success_at)
                   or (%(refresh_after)s::int is not null
                       and f.last_success_at < now()
                                             - make_interval(days => %(refresh_after)s::int)))
            order by {ORDERS[order]}
            limit %(limit)s
            """,  # noqa: S608 — `order` est validé contre ORDERS juste au-dessus
            {"refresh_after": refresh_after, "limit": limit},
        )
        return [row[0] for row in await cur.fetchall()]


async def backfill(
    conn: psycopg.AsyncConnection,
    client: TmdbClient,
    ids: list[int],
    *,
    concurrency: int = 4,
    stop: asyncio.Event | None = None,
    on_progress: Callable[[BackfillReport], None] | None = None,
) -> BackfillReport:
    """Collecte les séries données, `concurrency` en parallèle.

    S'arrête proprement si `stop` est armé : les collectes en cours vont à leur
    terme, les suivantes ne démarrent pas. Sur une passe de plusieurs dizaines
    d'heures, pouvoir interrompre sans corrompre l'état n'est pas un luxe — et
    `fetch_state` fait que la reprise repart d'où l'on s'est arrêté.
    """
    report = BackfillReport(selected=len(ids))
    queue: asyncio.Queue[int] = asyncio.Queue()
    for tv_id in ids:
        queue.put_nowait(tv_id)

    async def worker() -> None:
        while stop is None or not stop.is_set():
            try:
                tv_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                result = await collect_series(conn, client, tv_id)
            except Exception as exc:  # noqa: BLE001 — une série ne doit jamais tuer la passe
                log.warning("série %s : %s", tv_id, exc)
                report.failed += 1
            else:
                report.ok += int(result.ok)
                report.failed += int(not result.ok)
                report.requests += result.requests
                report.rows_written += result.rows_written
            report.done += 1
            if on_progress:
                on_progress(report)

    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    report.interrupted = bool(stop and stop.is_set() and report.remaining)
    return report
