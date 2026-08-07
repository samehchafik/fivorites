"""Le flux 2 : les séries qui existent dans Wikidata mais pas dans TMDB.

C'est le crawler de `doc/architecture-sourcing.md` §5. Il balaye les items
« série télévisée » sans identifiant TMDB, crée l'œuvre par QID, conserve le
brut (R1), et enrichit — Wikipédia par les sitelinks, TVmaze par `P8600` ou
`imdb_id`.

**La cible par défaut est le noyau dur** : les items sans identifiant TMDB *ni*
IMDb — injoignables par tout autre chemin (mesuré : 300 des 480 séries de
langue arabe). Les items à `imdb_id` sont exclus par défaut : ce sont très
probablement des séries présentes dans TMDB mais non reliées, que le flux 1
rattrape déjà par `P345` — les crawler créerait des doublons en masse.
`--avec-imdb` lève cette exclusion en connaissance de cause.

La réconciliation est portée par le pivot : si une série crawlée apparaît un
jour dans TMDB, l'enrichissement du flux 1 tentera d'attacher son QID à
l'œuvre TMDB, la collision sera journalisée « réconciliation à faire » — et
dans l'autre sens, un crawl qui retombe sur un QID déjà attaché réutilise
l'œuvre existante telle quelle.

La reprise fonctionne comme partout ailleurs : `fetch_state` (source
`wikidata`, kind `lookup`, source_id = QID) note chaque item regardé, et une
seconde passe saute ce qui l'a déjà été.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from fiv_sourcing import normalize, store
from fiv_sourcing.enrich import Cible, Clients, EnrichReport, _apres_wikidata, _entier, _persist
from fiv_sourcing.sources import wikidata

log = logging.getLogger(__name__)

# La page de balayage. Assez grande pour que 44 700 items tiennent en une
# vingtaine de requêtes, assez petite pour rester sous le timeout de Blazegraph.
PAGE = 2000


@dataclass(slots=True)
class CrawlReport:
    swept: int = 0  # items vus par le balayage
    selected: int = 0  # pas encore regardés
    done: int = 0
    enriched: int = 0  # œuvres ayant reçu au moins une source
    requests: int = 0
    rows_written: int = 0  # lignes de riche_source
    errors: int = 0
    interrupted: bool = False

    @property
    def remaining(self) -> int:
        return self.selected - self.done


async def sweep(
    clients: Clients,
    report: CrawlReport,
    *,
    langue: str | None = None,
    avec_imdb: bool = False,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """Tous les items du périmètre, par pages SPARQL ordonnées.

    `ORDER BY ?item` dans la requête n'est pas cosmétique : sans ordre stable,
    la pagination par OFFSET saute ou répète des items d'une page à l'autre.
    """
    items: list[dict[str, Any]] = []
    decalage = 0
    while True:
        resultat = await clients.wikidata.sweep_sans_tmdb(
            langue=langue, avec_imdb=avec_imdb, limite=PAGE, decalage=decalage
        )
        report.requests += 1
        if not resultat.ok:
            report.errors += 1
            log.warning("balayage wikidata en échec : %s", resultat.error or resultat.status)
            break
        page = wikidata.lire_sweep(resultat.payload)
        items.extend(page)
        decalage += PAGE
        if len(page) < PAGE or (max_items is not None and len(items) >= max_items):
            break
    report.swept = len(items)
    return items[:max_items] if max_items is not None else items


async def deja_regardes(conn: psycopg.AsyncConnection, qids: list[str]) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute(
            "select source_id from fetch_state "
            "where source = 'wikidata' and kind = 'lookup' and source_id = any(%s)",
            (qids,),
        )
        return {row[0] for row in await cur.fetchall()}


async def crawl_wikidata(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    items: list[dict[str, Any]],
    *,
    languages: tuple[str, ...] = ("fr", "en"),
    concurrency: int = 4,
    stop: asyncio.Event | None = None,
    on_progress: Callable[[CrawlReport], None] | None = None,
    report: CrawlReport | None = None,
) -> CrawlReport:
    """Crée et enrichit les œuvres des items donnés (déjà filtrés du déjà-vu)."""
    report = report or CrawlReport()
    report.selected = len(items)
    file: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for item in items:
        file.put_nowait(item)

    async def worker() -> None:
        while stop is None or not stop.is_set():
            try:
                item = file.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                detail = await _crawler_un_item(conn, clients, item, languages)
            except Exception as exc:  # noqa: BLE001 — un item ne tue pas la passe
                log.warning("item %s : %s", item.get("qid"), exc)
                report.errors += 1
            else:
                report.requests += detail.requests
                report.rows_written += detail.rows_written
                report.errors += len(detail.errors)
                report.enriched += int(bool(detail.sources))
            report.done += 1
            if on_progress:
                on_progress(report)

    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    report.interrupted = bool(stop and stop.is_set() and report.remaining)
    return report


async def _crawler_un_item(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    item: dict[str, Any],
    languages: tuple[str, ...],
) -> EnrichReport:
    """Un item : le lookup, l'œuvre, puis le même aval que le flux 1."""
    qid = item["qid"]
    detail = EnrichReport(tv_id=0)

    resultat = await clients.wikidata.by_qid(qid)
    detail.requests += 1
    if not resultat.ok:
        detail.errors.append(f"wikidata: {resultat.error or resultat.status}")
        await _persist(conn, wikidata.SOURCE, "lookup", qid, None, resultat)
        return detail

    faits = wikidata.lire_lookup(wikidata.canonicaliser(resultat.payload)) or {"qid": qid}
    # R1 : le lookup entre dans le brut, keyé par QID — le flux 1 utilise l'id
    # TMDB, les deux espaces de noms ne se croisent jamais.
    await _persist(conn, wikidata.SOURCE, "lookup", qid, None, resultat)

    oeuvre_id = await store.ensure_oeuvre_par_qid(conn, qid, titre=item.get("titre"))
    await store.attach_identifiers(
        conn,
        oeuvre_id,
        wikidata_qid=qid,
        imdb_id=faits.get("imdb") or item.get("imdb"),
        tvmaze_id=_entier(faits.get("tvmaze") or item.get("tvmaze")),
    )

    cible = Cible(oeuvre_id=oeuvre_id, cle=qid)
    detail.qid = qid
    detail.resolved_by = "sweep"
    await store.upsert_riche_source(
        conn,
        oeuvre_id=oeuvre_id,
        source=wikidata.SOURCE,
        source_id=qid,
        url=f"https://www.wikidata.org/wiki/{qid}",
        facts=normalize.depuis_wikidata(faits),
        resolved_by="sweep",
    )
    detail.rows_written += 1
    detail.sources.append(wikidata.SOURCE)

    # Le même aval que le flux 1 : sitelinks → articles, P8600/imdb → TVmaze.
    # `faits` porte déjà tvmaze/imdb ; le titre du sweep sert de dernier recours
    # à l'appariement TVmaze — qui exige de toute façon l'imdb pour décider.
    faits.setdefault("tvmaze", item.get("tvmaze"))
    faits.setdefault("imdb", item.get("imdb"))
    await _apres_wikidata(
        conn, clients, cible, faits, item.get("imdb"), item.get("titre"), languages, detail
    )
    return detail
