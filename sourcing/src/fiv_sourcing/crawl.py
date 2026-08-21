"""Le flux 2 : les œuvres qui entrent par Wikidata, pas par TMDB.

C'est le crawler de `doc/architecture-sourcing.md` §5, et il sert deux
univers qui n'y entrent pas pour la même raison :

  * les **séries hors TMDB** — il balaye les items « série télévisée » sans
    identifiant TMDB, crée l'œuvre par QID, écrit **la référence de base**
    dans `raw_source` — le lookup par QID, seule écriture du brut hors
    collecte TMDB (R1) — puis enrichit dans `riche_source` : Wikipédia par
    les sitelinks, TVmaze par `P8600` ou `imdb_id` ;
  * les **livres**, pour qui ce flux est le flux principal : il n'y a pas de
    TMDB du livre (doc/etude-sources-livres.md), et le crawler est leur
    porte d'entrée — même œuvre par QID, même référence de base, puis
    Wikipédia par les sitelinks et **Open Library** par `P648` ou par la
    recherche titre+auteur, pour les éditions et les traductions.

**La cible séries par défaut est le noyau dur** : les items sans identifiant
TMDB *ni* IMDb — injoignables par tout autre chemin (mesuré : 300 des 480
séries de langue arabe). Les items à `imdb_id` sont exclus par défaut : ce
sont très probablement des séries présentes dans TMDB mais non reliées, que
le flux 1 rattrape déjà par `P345` — les crawler créerait des doublons en
masse. `--avec-imdb` lève cette exclusion en connaissance de cause.

**La cible livres** n'a pas d'exclusion — rien d'autre ne les collecte —
mais un ordre : les œuvres les plus connues d'abord (sitelinks décroissants),
au-dessus d'un plancher qui écarte la traîne sans matière à notation.

La réconciliation est portée par le pivot : si une série crawlée apparaît un
jour dans TMDB, l'enrichissement du flux 1 tentera d'attacher son QID à
l'œuvre TMDB, la collision sera journalisée « réconciliation à faire » — et
dans l'autre sens, un crawl qui retombe sur un QID déjà attaché réutilise
l'œuvre existante telle quelle. Même mécanique pour l'OLID des livres.

La reprise fonctionne comme partout ailleurs : `fetch_state` (source
`wikidata`, kind `lookup` ou `lookup_book`, source_id = QID) note chaque item
regardé, et une seconde passe saute ce qui l'a déjà été.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from fiv_sourcing import normalize, store
from fiv_sourcing.enrich import (
    Cible,
    Clients,
    EnrichReport,
    _apres_wikidata,
    _entier,
    _noter,
    _persist,
)
from fiv_sourcing.sources import openlibrary, wikidata
from fiv_sourcing.univers import SERIES, Univers

log = logging.getLogger(__name__)

# La page de balayage. Assez grande pour que 44 700 items tiennent en une
# vingtaine de requêtes, assez petite pour rester sous le timeout de Blazegraph.
PAGE = 2000

# La page des livres est plus petite : leur balayage fait TRIER tout le corpus
# d'une langue par notoriété (sous-requête de SWEEP_LIVRES), là où celui des
# séries se contente de parcourir par identifiant. Mesuré le 2026-08-21 : la
# première page à froid d'un corpus riche (fr) prend ~35 s pour 500 lignes —
# 2 000 dépasserait le couperet de WDQS (60 s).
PAGE_LIVRES = 500


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
    univers: Univers = SERIES,
    langue: str | None = None,
    avec_imdb: bool = False,
    sitelinks_min: int = 5,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """Tous les items du périmètre, par pages SPARQL ordonnées.

    L'ordre stable n'est pas cosmétique : sans lui, la pagination par OFFSET
    saute ou répète des items d'une page à l'autre. Les séries s'ordonnent par
    `?item` ; les livres par sitelinks décroissants avec `?item` en départage
    (voir `SWEEP_LIVRES` pour le pourquoi).
    """
    items: list[dict[str, Any]] = []
    decalage = 0
    taille = PAGE_LIVRES if univers.openlibrary else PAGE
    while True:
        if univers.openlibrary:
            resultat = await clients.wikidata.sweep_livres(
                classes=univers.wikidata_classes,
                langue=langue,
                sitelinks_min=sitelinks_min,
                limite=taille,
                decalage=decalage,
            )
        else:
            resultat = await clients.wikidata.sweep_sans_tmdb(
                langue=langue, avec_imdb=avec_imdb, limite=taille, decalage=decalage
            )
        report.requests += 1
        if not resultat.ok:
            report.errors += 1
            log.warning("balayage wikidata en échec : %s", resultat.error or resultat.status)
            break
        if univers.openlibrary:
            page = wikidata.lire_sweep_livres(resultat.payload)
        else:
            page = wikidata.lire_sweep(resultat.payload)
        items.extend(page)
        decalage += taille
        if len(page) < taille or (max_items is not None and len(items) >= max_items):
            break
    report.swept = len(items)
    return items[:max_items] if max_items is not None else items


async def deja_regardes(
    conn: psycopg.AsyncConnection, qids: list[str], *, kind: str = "lookup"
) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute(
            "select source_id from fetch_state "
            "where source = 'wikidata' and kind = %s and source_id = any(%s)",
            (kind, qids),
        )
        return {row[0] for row in await cur.fetchall()}


async def crawl_wikidata(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    items: list[dict[str, Any]],
    *,
    univers: Univers = SERIES,
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
                detail = await _crawler_un_item(conn, clients, item, languages, univers)
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
    univers: Univers = SERIES,
) -> EnrichReport:
    """Un item : le lookup, l'œuvre, puis le même aval que le flux 1."""
    qid = item["qid"]
    detail = EnrichReport(tv_id=0)

    if univers.openlibrary:
        resultat = await clients.wikidata.by_qid_livre(qid)
    else:
        resultat = await clients.wikidata.by_qid(qid)
    detail.requests += 1
    if not resultat.ok:
        detail.errors.append(f"wikidata: {resultat.error or resultat.status}")
        await _noter(conn, wikidata.SOURCE, univers.lookup_kind, qid, resultat)
        return detail

    canonique = wikidata.canonicaliser(resultat.payload)
    if univers.openlibrary:
        faits = wikidata.lire_lookup_livre(canonique) or {"qid": qid}
    else:
        faits = wikidata.lire_lookup(canonique) or {"qid": qid}
    # R1 : pour une œuvre hors TMDB, ce lookup EST la référence de base — la
    # seule ligne de brut qu'elle aura jamais, l'équivalent de la fiche TMDB.
    # C'est la seule écriture de raw_source hors collecte TMDB : tout ce qui
    # suit (articles, TVmaze, Open Library) est de l'enrichissement et va dans
    # riche_source.
    await _persist(conn, wikidata.SOURCE, univers.lookup_kind, qid, None, resultat)

    oeuvre_id = await store.ensure_oeuvre_par_qid(
        conn, qid, titre=item.get("titre"), univers=univers.cle
    )
    await store.attach_identifiers(
        conn,
        oeuvre_id,
        wikidata_qid=qid,
        imdb_id=faits.get("imdb") or item.get("imdb"),
        tvmaze_id=_entier(faits.get("tvmaze") or item.get("tvmaze")),
        # Pas l'OLID : P648 pointe parfois une édition, voire une édition
        # orpheline — c'est `_openlibrary` qui attache l'identifiant, une
        # fois résolu en work.
    )

    cible = Cible(oeuvre_id=oeuvre_id, cle=qid)
    detail.qid = qid
    detail.resolved_by = "sweep"
    if univers.openlibrary:
        facts = normalize.depuis_wikidata_livre(faits)
    else:
        facts = normalize.depuis_wikidata(faits)
    await store.upsert_riche_source(
        conn,
        oeuvre_id=oeuvre_id,
        source=wikidata.SOURCE,
        source_id=qid,
        url=f"https://www.wikidata.org/wiki/{qid}",
        facts=facts,
        resolved_by="sweep",
    )
    detail.rows_written += 1
    detail.sources.append(wikidata.SOURCE)

    # Le même aval que le flux 1 : sitelinks → articles, puis la source propre
    # à l'univers — TVmaze pour une série (gardé par `univers.tvmaze`), Open
    # Library pour un livre. `faits` porte déjà tvmaze/imdb ; le titre du
    # sweep sert de dernier recours à l'appariement, qui exige de toute façon
    # l'imdb pour décider côté TVmaze.
    faits.setdefault("tvmaze", item.get("tvmaze"))
    faits.setdefault("imdb", item.get("imdb"))
    await _apres_wikidata(
        conn,
        clients,
        cible,
        faits,
        item.get("imdb"),
        item.get("titre"),
        languages,
        detail,
        univers,
    )
    if univers.openlibrary:
        await _openlibrary(conn, clients, cible, faits, item, detail)
    return detail


async def _openlibrary(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    cible: Cible,
    faits: dict[str, Any],
    item: dict[str, Any],
    detail: EnrichReport,
) -> None:
    """Le work et ses éditions — les traductions du livre.

    L'entrée suit le protocole mesuré (doc/etude-sources-livres.md, volet 1) :
    l'OLID de Wikidata (P648) d'abord, la recherche titre+auteur ensuite, le
    titre seul en dernier — c'est lui qui rattrape le catalogue arabe (60 %
    du corpus, quand P648 n'en couvre que 23 %). Pas d'identifiant commun
    pour confirmer, contrairement à TVmaze : le garde-fou est l'auteur quand
    on l'a, et un mauvais appariement se voit dans l'admin — la source et sa
    voie de résolution y sont affichées.
    """
    olid = faits.get("olid") or item.get("olid")
    voie = "p648" if olid else None

    if olid and olid.endswith("M"):
        # P648 pointe une édition, pas un work. L'édition connaît son work —
        # sauf orpheline, auquel cas on retombe sur la recherche par titre.
        resultat = await clients.openlibrary.book(olid)
        detail.requests += 1
        olid = openlibrary.work_de_l_edition(resultat.payload) if resultat.ok else None
        voie = "p648" if olid else None

    titre = item.get("titre")
    if olid is None and titre:
        resultat = None
        auteur = next((a.get("nom") for a in faits.get("auteurs") or [] if a.get("nom")), None)
        if auteur:
            resultat = await clients.openlibrary.search(titre, auteur)
            detail.requests += 1
            olid = openlibrary.lire_recherche(resultat.payload) if resultat.ok else None
            voie = "titre+auteur" if olid else None
        if olid is None:
            resultat = await clients.openlibrary.search(titre)
            detail.requests += 1
            olid = openlibrary.lire_recherche(resultat.payload) if resultat.ok else None
            voie = "titre" if olid else None
        if olid is None:
            # « On a cherché, il n'y a rien » est un état, pas une erreur —
            # 17 % du corpus arabe, mesuré. L'œuvre garde son QID et sa
            # matière Wikipédia ; l'OLID viendra d'une réconciliation, ou pas.
            await _noter(conn, openlibrary.SOURCE, "work", cible.cle, resultat)
            return
    if olid is None:
        return  # ni OLID ni titre : rien à chercher, donc rien à noter

    resultat = await clients.openlibrary.work(olid)
    detail.requests += 1
    redirige = openlibrary.redirection(resultat.payload) if resultat.ok else None
    if redirige:
        # Work fusionné : P648 pointe sur l'ancien identifiant, dont la page
        # d'éditions répond 404. On suit la redirection, une fois.
        olid = redirige
        resultat = await clients.openlibrary.work(olid)
        detail.requests += 1
    await _noter(conn, openlibrary.SOURCE, "work", cible.cle, resultat)
    work = openlibrary.lire_work(resultat.payload) if resultat.ok else None
    if work is None:
        detail.errors.append(f"openlibrary: {resultat.error or resultat.status}")
        return

    resultat_editions = await clients.openlibrary.editions(olid)
    detail.requests += 1
    editions = (
        openlibrary.lire_editions(resultat_editions.payload) if resultat_editions.ok else None
    )

    await store.attach_identifiers(conn, cible.oeuvre_id, openlibrary_id=olid)
    await store.upsert_riche_source(
        conn,
        oeuvre_id=cible.oeuvre_id,
        source=openlibrary.SOURCE,
        source_id=olid,
        url=f"{openlibrary.BASE_URL}/works/{olid}",
        content=work.get("description"),
        # La couverture du work, sinon celle d'une édition — un livre sans
        # aucun visuel rend la grille imprésentable, c'est mesuré.
        media=openlibrary.images(work) or openlibrary.images(editions or {}),
        facts=normalize.depuis_openlibrary(work, editions),
        resolved_by=voie,
    )
    detail.rows_written += 1
    detail.sources.append(openlibrary.SOURCE)
