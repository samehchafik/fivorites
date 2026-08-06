"""Enrichissement d'une série par les sources tierces — le lot 3.

Wikidata pour les faits et le raccordement, Wikipédia pour la matière textuelle,
TVmaze pour les dates et le calendrier. Aucun appel à TMDB : cette passe
s'ajoute à une collecte, elle ne la refait pas.

**Elle ne dépend pas non plus du jeton TMDB.** L'entrée dans Wikidata se fait
par `P4983`, qui se déduit de l'id qu'on a déjà dans `tmdb_catalog`. Une série
jamais collectée peut donc être enrichie — on aura ses faits et son texte, mais
pas sa fiche. C'est délibéré : ça découple les deux chantiers, et ça permet
d'avancer pendant qu'un jeton est refusé.

L'enchaînement, et ce que chaque étape débloque pour la suivante :

    tmdb_catalog.id ──P4983──> Wikidata ──> QID, imdb_id, id TVmaze, faits
                                  │
                                  ├── sitelinks ──> Wikipédia (n langues)
                                  └── P8600 / imdb_id ──> TVmaze

Le brut de chaque réponse va dans `raw_source` — une réponse HTTP, une ligne,
l'invariant ne change pas. `series_source` en est la dérivation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fiv_sourcing import store
from fiv_sourcing.config import Settings
from fiv_sourcing.http import FetchResult, HttpFetcher
from fiv_sourcing.sources import tvmaze, wikidata, wikipedia

log = logging.getLogger(__name__)

# Un 401/403 ne dit rien sur l'œuvre, seulement sur notre configuration —
# même raisonnement que dans la collecte TMDB.
NOT_ABOUT_THE_WORK = frozenset({401, 403})


@dataclass(slots=True)
class EnrichReport:
    tv_id: int
    qid: str | None = None
    resolved_by: str | None = None
    requests: int = 0
    rows_written: int = 0  # lignes de raw_source
    sources: list[str] = field(default_factory=list)  # ce qui a été rempli
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.sources) and not self.errors


@dataclass(slots=True)
class Clients:
    wikidata: wikidata.WikidataClient
    wikipedia: wikipedia.WikipediaClient
    tvmaze: tvmaze.TvmazeClient


def build_clients(fetcher: HttpFetcher) -> Clients:
    return Clients(
        wikidata=wikidata.WikidataClient(fetcher),
        wikipedia=wikipedia.WikipediaClient(fetcher),
        tvmaze=tvmaze.TvmazeClient(fetcher),
    )


def build_fetcher(settings: Settings) -> HttpFetcher:
    """Un client distinct de celui de TMDB.

    Deux raisons de ne pas réutiliser l'autre : il porte l'en-tête
    d'authentification TMDB, qu'on n'envoie pas à Wikimedia ni à TVmaze ; et le
    débit n'est pas le même — 20 req/s conviennent à une API commerciale, pas au
    service SPARQL de Wikidata, qui est gratuit et partagé.
    """
    return HttpFetcher(
        rate_limit=settings.enrich_rate_limit,
        timeout=settings.http_timeout,
        max_attempts=settings.http_max_attempts,
        user_agent=settings.http_user_agent,
    )


async def enrich_series(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    tv_id: int,
    *,
    languages: tuple[str, ...] = ("fr", "en"),
) -> EnrichReport:
    report = EnrichReport(tv_id=tv_id)

    titre = await _titre_du_catalogue(conn, tv_id)
    imdb_connu = await _imdb_depuis_la_collecte(conn, tv_id)
    faits = await _wikidata(conn, clients, tv_id, imdb_connu, report)

    await _apres_wikidata(conn, clients, tv_id, faits, imdb_connu, titre, languages, report)
    return report


async def _apres_wikidata(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    tv_id: int,
    faits: dict[str, Any] | None,
    imdb_connu: str | None,
    titre: str | None,
    languages: tuple[str, ...],
    report: EnrichReport,
) -> None:
    """Ce qui suit la résolution, identique à l'unité et en masse.

    Seule la façon d'obtenir `faits` diffère entre les deux : une requête SPARQL
    par série d'un côté, une pour cent de l'autre.
    """
    if faits is None:
        # Sans item Wikidata, il reste TVmaze — par l'imdb_id de la collecte, ou
        # par le titre si cet identifiant existe pour départager. Au dixième
        # décile de popularité, rien n'aboutit : c'est mesuré, pas une anomalie.
        await _tvmaze(conn, clients, tv_id, None, imdb_connu, titre, report)
        return

    articles = await _sitelinks(conn, clients, faits["qid"], report)
    imdb = faits.get("imdb") or imdb_connu

    await asyncio.gather(
        _wikipedia(conn, clients, tv_id, articles, languages, report),
        _tvmaze(conn, clients, tv_id, faits.get("tvmaze"), imdb, titre, report),
    )


# --------------------------------------------------------------------- étapes
async def _wikidata(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    tv_id: int,
    imdb_connu: str | None,
    report: EnrichReport,
) -> dict[str, Any] | None:
    """P4983 d'abord, P345 en second recours. Voir le module pour le pourquoi."""
    resultat = await clients.wikidata.by_tmdb(tv_id)
    report.requests += 1
    voie = "p4983"
    faits = wikidata.lire_lookup(resultat.payload) if resultat.ok else None

    if faits is None and imdb_connu:
        resultat = await clients.wikidata.by_imdb(imdb_connu)
        report.requests += 1
        voie = "p345"
        faits = wikidata.lire_lookup(resultat.payload) if resultat.ok else None

    await _persist(conn, wikidata.SOURCE, "lookup", str(tv_id), None, resultat, report)
    if not resultat.ok:
        report.errors.append(f"wikidata: {resultat.error or resultat.status}")
    if faits is None:
        return None

    await _enregistrer_wikidata(conn, tv_id, faits, voie, report)
    return faits


async def _enregistrer_wikidata(
    conn: psycopg.AsyncConnection,
    tv_id: int,
    faits: dict[str, Any],
    voie: str,
    report: EnrichReport,
) -> None:
    report.qid = faits["qid"]
    report.resolved_by = voie
    await store.upsert_series_source(
        conn,
        id_tmdb=tv_id,
        source=wikidata.SOURCE,
        source_id=faits["qid"],
        url=f"https://www.wikidata.org/wiki/{faits['qid']}",
        # Wikidata n'apporte pas de texte : ses faits partiront vers la couche 1
        # au lot 4. Ce qu'on retient ici, c'est le raccordement.
        content=None,
        media=[],
        resolved_by=voie,
    )
    report.sources.append(wikidata.SOURCE)


async def _sitelinks(
    conn: psycopg.AsyncConnection, clients: Clients, qid: str, report: EnrichReport
) -> dict[str, str]:
    resultat = await clients.wikidata.entity(qid)
    report.requests += 1
    await _persist(conn, wikidata.SOURCE, "entity", qid, None, resultat, report)
    if not resultat.ok:
        report.errors.append(f"wikidata/entity: {resultat.error or resultat.status}")
        return {}
    return wikidata.lire_sitelinks(resultat.payload, qid)


async def _wikipedia(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    tv_id: int,
    articles: dict[str, str],
    languages: tuple[str, ...],
    report: EnrichReport,
) -> None:
    for lang in languages:
        titre = articles.get(lang)
        if not titre:
            continue
        resultat = await clients.wikipedia.article(lang, titre)
        report.requests += 1
        await _persist(conn, wikipedia.SOURCE, "article", titre, lang, resultat, report)
        if not resultat.ok:
            report.errors.append(f"wikipedia/{lang}: {resultat.error or resultat.status}")
            continue

        lu = wikipedia.lire_article(resultat.payload)
        if lu is None:
            continue
        titre_canonique, texte = lu
        await store.upsert_series_source(
            conn,
            id_tmdb=tv_id,
            source=wikipedia.SOURCE,
            lang=lang,
            source_id=titre_canonique,
            url=f"https://{lang}.wikipedia.org/wiki/{titre_canonique.replace(' ', '_')}",
            content=texte,
            media=[],
            resolved_by="sitelink",
        )
        report.sources.append(f"{wikipedia.SOURCE}/{lang}")


async def _tvmaze(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    tv_id: int,
    tvmaze_id: str | None,
    imdb: str | None,
    titre: str | None,
    report: EnrichReport,
) -> None:
    show_id, voie = tvmaze_id, "p8600"

    if show_id is None and imdb:
        resultat = await clients.tvmaze.by_imdb(imdb)
        report.requests += 1
        if resultat.ok and resultat.payload:
            show_id, voie = resultat.payload.get("id"), "imdb"

    # `imdb` est exigé ici, et pas seulement pour départager : c'est lui qui
    # **décide**. Sans lui, `choisir_par_titre` refusera tous les candidats — la
    # recherche serait donc une requête sûre d'être inutile. Sur les 60 % du
    # catalogue sans item Wikidata, ça ferait autant d'appels gratuits à un
    # service gratuit, pour rien.
    if show_id is None and titre and imdb:
        resultat = await clients.tvmaze.search(titre)
        report.requests += 1
        show_id, voie = tvmaze.choisir_par_titre(resultat.payload, imdb), "title"

    if show_id is None:
        return

    resultat = await clients.tvmaze.show(show_id)
    report.requests += 1
    await _persist(conn, tvmaze.SOURCE, "show", str(show_id), None, resultat, report)
    if not resultat.ok:
        report.errors.append(f"tvmaze: {resultat.error or resultat.status}")
        return

    lu = tvmaze.lire_show(resultat.payload)
    if lu is None:
        return
    await store.upsert_series_source(
        conn,
        id_tmdb=tv_id,
        source=tvmaze.SOURCE,
        source_id=str(lu["id"]),
        url=lu.get("url"),
        content=lu.get("texte"),
        media=tvmaze.images(resultat.payload),
        resolved_by=voie,
    )
    report.sources.append(tvmaze.SOURCE)


# ------------------------------------------------------------------ en masse
ORDERS = {
    "id": "c.id",
    "random": "random()",
    "popularity": "c.popularity desc, c.id",
}


@dataclass(slots=True)
class EnrichAllReport:
    selected: int = 0
    done: int = 0
    resolved: int = 0  # séries ayant un item Wikidata
    enriched: int = 0  # séries ayant reçu au moins une source
    requests: int = 0
    rows_written: int = 0
    errors: int = 0
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
    """Séries encore sans complément.

    Le critère est `fetch_state`, **pas** la présence d'une ligne dans
    `series_source` : la majorité des séries n'a pas d'item Wikidata, donc ne
    produira jamais de ligne. Se fier à `series_source` ferait retenter
    indéfiniment tout le fond de catalogue à chaque passe.

    `fetch_state` répond à la bonne question — « a-t-on déjà regardé ? » — et
    c'est exactement ce pour quoi il existe.
    """
    if order not in ORDERS:
        raise ValueError(f"tri inconnu : {order} (attendu : {', '.join(ORDERS)})")

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            select c.id
            from tmdb_catalog c
            left join fetch_state f
                   on f.source = 'wikidata' and f.kind = 'lookup'
                  and f.source_id = c.id::text
            where f.last_fetched_at is null
               or (%(refresh_after)s::int is not null
                   and f.last_fetched_at < now()
                                         - make_interval(days => %(refresh_after)s::int))
            order by {ORDERS[order]}
            limit %(limit)s
            """,  # noqa: S608 — `order` est validé contre ORDERS juste au-dessus
            {"refresh_after": refresh_after, "limit": limit},
        )
        return [row[0] for row in await cur.fetchall()]


async def enrich_all(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    ids: list[int],
    *,
    languages: tuple[str, ...] = ("fr", "en"),
    lot: int = 100,
    concurrency: int = 4,
    stop: asyncio.Event | None = None,
    on_progress: Callable[[EnrichAllReport], None] | None = None,
) -> EnrichAllReport:
    """Enrichit une liste de séries, par lots.

    Deux temps, et c'est ce qui rend la passe tenable :

    1. **une requête SPARQL pour cent séries** — c'est la seule étape que toutes
       subissent, et la seule qu'on ne peut pas éviter. Par cent, le catalogue
       entier coûte 2 300 requêtes au lieu de 228 000 ;
    2. **le détail, uniquement pour celles qui ont un item** — sitelinks,
       articles, TVmaze. Environ trois séries sur dix, et c'est là que passe
       l'essentiel du temps.

    Les séries sans item mais dont la collecte TMDB a donné un `imdb_id` passent
    quand même par TVmaze : c'est le seul rattrapage qui reste, et il fonctionne.
    """
    report = EnrichAllReport(selected=len(ids))

    for depart in range(0, len(ids), lot):
        if stop is not None and stop.is_set():
            break
        tranche = ids[depart : depart + lot]
        faits_par_id = await _resoudre_le_lot(conn, clients, tranche, report)
        titres = await _titres_du_catalogue(conn, tranche)
        imdbs = await _imdbs_depuis_la_collecte(conn, tranche)

        await _traiter_la_tranche(
            conn,
            clients,
            tranche,
            faits_par_id=faits_par_id,
            titres=titres,
            imdbs=imdbs,
            languages=languages,
            concurrency=concurrency,
            stop=stop,
            report=report,
            on_progress=on_progress,
        )
        if on_progress:
            on_progress(report)

    report.interrupted = bool(stop and stop.is_set() and report.remaining)
    return report


async def _traiter_la_tranche(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    tranche: list[int],
    *,
    faits_par_id: dict[int, dict[str, Any]],
    titres: dict[int, str],
    imdbs: dict[int, str],
    languages: tuple[str, ...],
    concurrency: int,
    stop: asyncio.Event | None,
    report: EnrichAllReport,
    on_progress: Callable[[EnrichAllReport], None] | None,
) -> None:
    """Le détail des séries d'une tranche, `concurrency` en parallèle.

    Fonction séparée et non fermeture dans la boucle : capturer les
    dictionnaires de la tranche courante dans un `worker` défini sur place
    marcherait tant qu'on attend avant l'itération suivante, et casserait
    silencieusement le jour où quelqu'un enlèverait cette attente.
    """
    file: asyncio.Queue[int] = asyncio.Queue()
    for tv_id in tranche:
        # Sans item et sans imdb_id, il n'y a rien à tenter : la recherche par
        # titre ne pourrait rien confirmer. Le passage est déjà noté.
        if tv_id in faits_par_id or imdbs.get(tv_id):
            file.put_nowait(tv_id)
        else:
            report.done += 1

    async def worker() -> None:
        while stop is None or not stop.is_set():
            try:
                tv_id = file.get_nowait()
            except asyncio.QueueEmpty:
                return
            detail = EnrichReport(tv_id=tv_id)
            if tv_id in faits_par_id:
                # La ligne `wikidata` a été écrite à la résolution du lot, donc
                # hors de ce rapport-ci. Sans ce report, `enriched` compterait
                # moins de séries qu'il n'y en a dans `series_source` — un écart
                # qu'on chercherait longtemps.
                detail.sources.append(wikidata.SOURCE)
            try:
                await _apres_wikidata(
                    conn,
                    clients,
                    tv_id,
                    faits_par_id.get(tv_id),
                    imdbs.get(tv_id),
                    titres.get(tv_id),
                    languages,
                    detail,
                )
            except Exception as exc:  # noqa: BLE001 — une série ne tue pas la passe
                log.warning("série %s : %s", tv_id, exc)
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


async def _resoudre_le_lot(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    ids: list[int],
    report: EnrichAllReport,
) -> dict[int, dict[str, Any]]:
    """Une requête, cent séries — puis on redécoupe par série pour le stockage."""
    resultat = await clients.wikidata.by_tmdb_lot(ids)
    report.requests += 1
    if not resultat.ok:
        report.errors += 1
        log.warning("lot wikidata en échec : %s", resultat.error or resultat.status)
        return {}

    lignes = wikidata.lignes_par_id(resultat.payload)
    faits_par_id = wikidata.lire_lookup_lot(resultat.payload)

    for tv_id in ids:
        ligne = lignes.get(tv_id)
        # `enveloppe` réemballe au format d'une réponse mono-série : le lot est
        # une optimisation de transport, l'unité conservée reste l'objet.
        payload = wikidata.enveloppe(ligne) if ligne else {"results": {"bindings": []}}
        written = await store.store_raw(
            conn,
            source=wikidata.SOURCE,
            kind="lookup",
            source_id=str(tv_id),
            lang=None,
            http_status=resultat.status,
            payload=payload,
        )
        await store.mark_fetch(
            conn,
            source=wikidata.SOURCE,
            kind="lookup",
            source_id=str(tv_id),
            http_status=resultat.status,
            changed=written,
        )
        report.rows_written += int(written)

    for tv_id, faits in faits_par_id.items():
        detail = EnrichReport(tv_id=tv_id)
        await _enregistrer_wikidata(conn, tv_id, faits, "p4983", detail)
    report.resolved += len(faits_par_id)
    return faits_par_id


async def _titres_du_catalogue(conn: psycopg.AsyncConnection, ids: list[int]) -> dict[int, str]:
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, original_name from tmdb_catalog "
            "where id = any(%s) and original_name is not null",
            (ids,),
        )
        return dict(await cur.fetchall())


async def _imdbs_depuis_la_collecte(
    conn: psycopg.AsyncConnection, ids: list[int]
) -> dict[int, str]:
    """Les `imdb_id` déjà collectés, en une requête pour tout le lot.

    Vide tant que la collecte TMDB n'a pas tourné — l'enrichissement n'en dépend
    pas, il en profite quand c'est là.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select distinct on (source_id)
                   source_id::int,
                   payload -> 'external_ids' ->> 'imdb_id'
            from raw_source
            where source = 'tmdb' and kind = 'tv'
              and source_id = any(%s)
              and http_status between 200 and 299
            order by source_id, fetched_at desc
            """,
            ([str(i) for i in ids],),
        )
        return {row[0]: row[1] for row in await cur.fetchall() if row[1]}


# ---------------------------------------------------------------------- outils
async def _titre_du_catalogue(conn: psycopg.AsyncConnection, tv_id: int) -> str | None:
    """Le titre original, lu dans l'inventaire.

    Pas dans `raw_source` : l'inventaire est rempli par l'export public, donc il
    est là même quand rien n'a été collecté. C'est ce qui permet à la recherche
    TVmaze par titre de fonctionner sans jeton TMDB.
    """
    async with conn.cursor() as cur:
        await cur.execute("select original_name from tmdb_catalog where id = %s", (tv_id,))
        row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def _imdb_depuis_la_collecte(conn: psycopg.AsyncConnection, tv_id: int) -> str | None:
    """L'`imdb_id` que TMDB a donné, s'il a été collecté.

    Facultatif : l'enrichissement fonctionne sans, par `P4983`. Mais quand il
    est là, il ouvre la seconde entrée Wikidata et surtout il **décide** de
    l'appariement TVmaze.
    """
    payload = await store.latest_payload(conn, source="tmdb", kind="tv", source_id=str(tv_id))
    return ((payload or {}).get("external_ids") or {}).get("imdb_id") or None


async def _persist(
    conn: psycopg.AsyncConnection,
    source: str,
    kind: str,
    source_id: str,
    lang: str | None,
    resultat: FetchResult,
    report: EnrichReport,
) -> None:
    written = False
    if resultat.status not in NOT_ABOUT_THE_WORK:
        written = await store.store_raw(
            conn,
            source=source,
            kind=kind,
            source_id=source_id,
            lang=lang,
            http_status=resultat.status,
            payload=resultat.payload,
        )
    await store.mark_fetch(
        conn,
        source=source,
        kind=kind,
        source_id=source_id,
        http_status=resultat.status,
        changed=written,
        error=resultat.error,
    )
    report.rows_written += int(written)
