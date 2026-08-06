"""Enrichissement d'une série par les sources tierces — le lot 3.

Wikidata pour les faits et le raccordement, Wikipédia pour la matière textuelle,
TVmaze pour les dates et le calendrier.

Les règles sont celles de `doc/architecture-sourcing.md` :

  * **R1** — le brut de Wikidata et Wikipédia va dans `raw_source`, comme celui
    de TMDB. Jamais celui de TVmaze : enrichissement pur, rejouer = réinterroger.
  * **R2** — `riche_source` n'est jamais une copie du brut, c'est une
    interprétation : les `facts` au format canonique, le texte utile.
  * **R5** — les faits passent par `normalize.py`, jamais par le format
    propriétaire d'une source.

Une série doit être **collectée** avant d'être enrichie sur ce chemin-ci —
`riche_source` se raccroche à la fiche ; le flux hors-TMDB (crawler) entrera
par le pivot `oeuvre`.

L'enchaînement, et ce que chaque étape débloque pour la suivante :

    fiche raw_source ──P4983──> Wikidata ──> QID, imdb_id, id TVmaze, faits
                                   │
                                   ├── sitelinks ──> Wikipédia (n langues)
                                   └── P8600 / imdb_id ──> TVmaze

Seul l'état de reprise passe par `fetch_state` — « a-t-on déjà regardé ? » —
qui est de l'état, pas du brut.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fiv_sourcing import normalize, store
from fiv_sourcing.config import Settings
from fiv_sourcing.http import FetchResult, HttpFetcher
from fiv_sourcing.sources import tvmaze, wikidata, wikipedia

log = logging.getLogger(__name__)


@dataclass(slots=True)
class EnrichReport:
    tv_id: int
    qid: str | None = None
    resolved_by: str | None = None
    requests: int = 0
    rows_written: int = 0  # lignes de riche_source
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
    """Un client distinct de celui de TMDB, et un débit par hôte.

    Deux raisons de ne pas réutiliser l'autre : il porte l'en-tête
    d'authentification TMDB, qu'on n'envoie ni à Wikimedia ni à TVmaze ; et le
    débit n'est pas le même — 20 req/s conviennent à une API commerciale, pas à
    des services gratuits et partagés.

    Le débit est ensuite **par hôte** et non global, parce que les trois n'ont
    pas la même tolérance. TVmaze documente « at least 20 calls every 10 seconds
    per IP » et pèse environ 40 % des requêtes : sous un plafond commun, soit on
    le dépasse, soit on impose son rythme à Wikimedia qui encaisse bien plus.
    """
    return HttpFetcher(
        rate_limit=settings.enrich_rate_limit,
        rate_limits={"api.tvmaze.com": settings.tvmaze_rate_limit},
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

    fiche_id = (await store.latest_fiche_ids(conn, [tv_id])).get(tv_id)
    if fiche_id is None:
        report.errors.append("série non collectée — `tmdb fetch` d'abord")
        return report

    cible = Cible(
        tv_id=tv_id,
        oeuvre_id=(await store.ensure_oeuvres(conn, [tv_id]))[tv_id],
        fiche_id=fiche_id,
    )
    titre = await _titre_du_catalogue(conn, tv_id)
    imdb_connu = await _imdb_depuis_la_collecte(conn, tv_id)
    faits = await _wikidata(conn, clients, cible, imdb_connu, report)

    await _apres_wikidata(conn, clients, cible, faits, imdb_connu, titre, languages, report)
    return report


@dataclass(slots=True, frozen=True)
class Cible:
    """Une série à enrichir : ses identités internes.

    `oeuvre_id` est le pivot — c'est lui qui attache les lignes entre elles,
    et le seul champ toujours présent. `tv_id` et `fiche_id` sont l'ancrage
    TMDB : renseignés sur le flux 1, nuls sur le flux 2 (crawler hors-TMDB).
    """

    oeuvre_id: int
    tv_id: int | None = None
    fiche_id: int | None = None


async def _apres_wikidata(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    cible: Cible,
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
        await _tvmaze(conn, clients, cible, None, imdb_connu, titre, report)
        return

    articles = await _sitelinks(conn, clients, faits["qid"], report)
    imdb = faits.get("imdb") or imdb_connu

    await asyncio.gather(
        _wikipedia(conn, clients, cible, articles, languages, report),
        _tvmaze(conn, clients, cible, faits.get("tvmaze"), imdb, titre, report),
    )


# --------------------------------------------------------------------- étapes
async def _wikidata(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    cible: Cible,
    imdb_connu: str | None,
    report: EnrichReport,
) -> dict[str, Any] | None:
    """P4983 d'abord, P345 en second recours. Voir le module pour le pourquoi."""
    resultat = await clients.wikidata.by_tmdb(cible.tv_id)
    report.requests += 1
    voie = "p4983"
    # `canonicaliser` avant tout : l'ordre des GROUP_CONCAT n'est pas garanti
    # par Blazegraph, et sans tri chaque rejeu écrirait une ligne de brut de
    # plus pour un contenu identique (R2).
    faits = wikidata.lire_lookup(wikidata.canonicaliser(resultat.payload)) if resultat.ok else None

    if faits is None and imdb_connu:
        resultat = await clients.wikidata.by_imdb(imdb_connu)
        report.requests += 1
        voie = "p345"
        faits = (
            wikidata.lire_lookup(wikidata.canonicaliser(resultat.payload)) if resultat.ok else None
        )

    # R1 : la réponse qui porte quelque chose va dans le brut. Une réponse
    # vide n'apprend rien que fetch_state ne dise déjà — passage noté seulement.
    if faits is not None:
        await _persist(conn, wikidata.SOURCE, "lookup", str(cible.tv_id), None, resultat)
    else:
        await _noter(conn, wikidata.SOURCE, "lookup", str(cible.tv_id), resultat)
    if not resultat.ok:
        report.errors.append(f"wikidata: {resultat.error or resultat.status}")
    if faits is None:
        return None

    await _enregistrer_wikidata(conn, cible, faits, voie, report)
    return faits


async def _enregistrer_wikidata(
    conn: psycopg.AsyncConnection,
    cible: Cible,
    faits: dict[str, Any],
    voie: str,
    report: EnrichReport,
) -> None:
    report.qid = faits["qid"]
    report.resolved_by = voie
    # Les identifiants appris remontent sur le pivot : c'est lui qui permettra
    # la réconciliation le jour où une œuvre saisie hors TMDB y apparaît.
    await store.attach_identifiers(
        conn,
        cible.oeuvre_id,
        wikidata_qid=faits["qid"],
        imdb_id=faits.get("imdb"),
        tvmaze_id=_entier(faits.get("tvmaze")),
    )
    await store.upsert_riche_source(
        conn,
        oeuvre_id=cible.oeuvre_id,
        raw_source_id=cible.fiche_id,
        tv_id=cible.tv_id,
        source=wikidata.SOURCE,
        source_id=faits["qid"],
        url=f"https://www.wikidata.org/wiki/{faits['qid']}",
        content=None,
        media=[],
        # Au format canonique (R5) : la couche 1 lira ces clés-là, jamais le
        # format propriétaire de la source.
        facts=normalize.depuis_wikidata(faits),
        resolved_by=voie,
    )
    report.rows_written += 1
    report.sources.append(wikidata.SOURCE)


async def _sitelinks(
    conn: psycopg.AsyncConnection, clients: Clients, qid: str, report: EnrichReport
) -> dict[str, str]:
    resultat = await clients.wikidata.entity(qid)
    report.requests += 1
    if not resultat.ok:
        report.errors.append(f"wikidata/entity: {resultat.error or resultat.status}")
        return {}
    await _persist(conn, wikidata.SOURCE, "entity", qid, None, resultat)
    return wikidata.lire_sitelinks(resultat.payload, qid)


async def _wikipedia(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    cible: Cible,
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
        if not resultat.ok:
            report.errors.append(f"wikipedia/{lang}: {resultat.error or resultat.status}")
            continue

        # R1 : l'article complet vit dans le brut — c'est ce qui rend
        # l'extraction (R2, sections utiles) rejouable hors ligne.
        await _persist(conn, wikipedia.SOURCE, "article", titre, lang, resultat)
        lu = wikipedia.lire_article(resultat.payload)
        if lu is None:
            continue
        titre_canonique, texte = lu
        await store.upsert_riche_source(
            conn,
            oeuvre_id=cible.oeuvre_id,
            raw_source_id=cible.fiche_id,
            tv_id=cible.tv_id,
            source=wikipedia.SOURCE,
            lang=lang,
            source_id=titre_canonique,
            url=f"https://{lang}.wikipedia.org/wiki/{titre_canonique.replace(' ', '_')}",
            content=texte,
            media=[],
            resolved_by="sitelink",
        )
        report.rows_written += 1
        report.sources.append(f"{wikipedia.SOURCE}/{lang}")


async def _tvmaze(
    conn: psycopg.AsyncConnection,
    clients: Clients,
    cible: Cible,
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
    # recherche serait donc une requête sûre d'être inutile.
    if show_id is None and titre and imdb:
        resultat = await clients.tvmaze.search(titre)
        report.requests += 1
        show_id, voie = tvmaze.choisir_par_titre(resultat.payload, imdb), "title"

    if show_id is None:
        return

    resultat = await clients.tvmaze.show(show_id)
    report.requests += 1
    if not resultat.ok:
        report.errors.append(f"tvmaze: {resultat.error or resultat.status}")
        return

    lu = tvmaze.lire_show(resultat.payload)
    if lu is None:
        return
    await store.attach_identifiers(
        conn, cible.oeuvre_id, imdb_id=lu.get("imdb"), tvmaze_id=_entier(lu.get("id"))
    )
    await store.upsert_riche_source(
        conn,
        oeuvre_id=cible.oeuvre_id,
        raw_source_id=cible.fiche_id,
        tv_id=cible.tv_id,
        source=tvmaze.SOURCE,
        source_id=str(lu["id"]),
        url=lu.get("url"),
        content=lu.get("texte"),
        media=tvmaze.images(resultat.payload),
        # Au format canonique (R5). TVmaze n'a pas de brut (R1, enrichissement
        # pur) : ces faits n'existent qu'ici, et rejouer = réinterroger.
        facts=normalize.depuis_tvmaze(lu),
        resolved_by=voie,
    )
    report.rows_written += 1
    report.sources.append(tvmaze.SOURCE)


# ------------------------------------------------------------------ en masse
ORDERS = {
    "id": "c.id",
    "random": "random()",
    "popularity": "c.popularity desc, c.id",
    # « Les plus récentes, et à date égale les plus populaires. » La popularité
    # seule ne le remplace pas : une série de 2015 très consultée passerait
    # avant une nouveauté, ce qui est l'inverse de l'intention.
    "recent": "c.first_air_date desc nulls last, c.popularity desc, c.id",
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
    """Séries collectées et encore sans complément.

    **Collectées** : `riche_source` référence la fiche de `raw_source`, donc une
    série sans fiche n'est pas enrichissable — elle entrera dans la sélection
    une fois la collecte passée.

    Le critère de reprise est `fetch_state`, **pas** la présence d'une ligne
    dans `riche_source` : la majorité des séries n'a pas d'item Wikidata, donc
    ne produira jamais de ligne. S'y fier ferait retenter indéfiniment tout le
    fond de catalogue à chaque passe.
    """
    if order not in ORDERS:
        raise ValueError(f"tri inconnu : {order} (attendu : {', '.join(ORDERS)})")

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            select c.id
            from tmdb_catalog c
            join fetch_state collecte
                   on collecte.source = 'tmdb' and collecte.kind = 'tv'
                  and collecte.source_id = c.id::text
                  and collecte.last_success_at is not null
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
    """Enrichit une liste de séries collectées, par lots.

    Deux temps, et c'est ce qui rend la passe tenable :

    1. **une requête SPARQL pour cent séries** — c'est la seule étape que toutes
       subissent. Par cent, le catalogue entier coûte 2 300 requêtes au lieu de
       228 000 ;
    2. **le détail, uniquement pour celles qui ont un item** — sitelinks,
       articles, TVmaze — ou dont la collecte a donné un `imdb_id`.
    """
    report = EnrichAllReport(selected=len(ids))

    for depart in range(0, len(ids), lot):
        if stop is not None and stop.is_set():
            break
        tranche = ids[depart : depart + lot]
        fiches = await store.latest_fiche_ids(conn, tranche)
        oeuvres = await store.ensure_oeuvres(conn, [i for i in tranche if i in fiches])
        cibles = {
            tv_id: Cible(tv_id=tv_id, oeuvre_id=oeuvres[tv_id], fiche_id=fiches[tv_id])
            for tv_id in tranche
            if tv_id in fiches
        }
        faits_par_id = await _resoudre_le_lot(conn, clients, tranche, cibles, report)
        titres = await _titres_du_catalogue(conn, tranche)
        imdbs = await _imdbs_depuis_la_collecte(conn, tranche)

        await _traiter_la_tranche(
            conn,
            clients,
            tranche,
            cibles=cibles,
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
    cibles: dict[int, Cible],
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
        # Sans fiche collectée, rien à raccrocher. Sans item et sans imdb_id,
        # rien à tenter : la recherche par titre ne pourrait rien confirmer.
        # Le passage est déjà noté dans fetch_state.
        if tv_id in cibles and (tv_id in faits_par_id or imdbs.get(tv_id)):
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
                # moins de séries qu'il n'y en a dans `riche_source`.
                detail.sources.append(wikidata.SOURCE)
            try:
                await _apres_wikidata(
                    conn,
                    clients,
                    cibles[tv_id],
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
    cibles: dict[int, Cible],
    report: EnrichAllReport,
) -> dict[int, dict[str, Any]]:
    """Une requête SPARQL pour cent séries, et le passage noté pour chacune."""
    resultat = await clients.wikidata.by_tmdb_lot(ids)
    report.requests += 1
    if not resultat.ok:
        report.errors += 1
        log.warning("lot wikidata en échec : %s", resultat.error or resultat.status)
        return {}

    # Même canonicalisation qu'à l'unité : sans elle, chaque rejeu du lot
    # écrirait cent lignes de brut pour un contenu identique.
    payload = wikidata.canonicaliser(resultat.payload)
    faits_par_id = wikidata.lire_lookup_lot(payload)
    lignes = wikidata.lignes_par_id(payload)

    for tv_id in ids:
        # R1/R2 : la ligne du lot est réemballée au format mono-série avant
        # d'entrer dans le brut — le lot est une optimisation de transport,
        # l'unité conservée reste l'objet. Rien pour les séries sans item.
        ligne = lignes.get(tv_id)
        if ligne is not None:
            await store.store_raw(
                conn,
                source=wikidata.SOURCE,
                kind="lookup",
                source_id=str(tv_id),
                lang=None,
                http_status=resultat.status,
                payload=wikidata.enveloppe(ligne),
            )
        await store.mark_fetch(
            conn,
            source=wikidata.SOURCE,
            kind="lookup",
            source_id=str(tv_id),
            http_status=resultat.status,
            changed=tv_id in faits_par_id,
        )

    for tv_id, faits in faits_par_id.items():
        cible = cibles.get(tv_id)
        if cible is None:
            continue
        detail = EnrichReport(tv_id=tv_id)
        await _enregistrer_wikidata(conn, cible, faits, "p4983", detail)
        report.rows_written += detail.rows_written
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
    """Les `imdb_id` des fiches collectées, en une requête pour tout le lot."""
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
    async with conn.cursor() as cur:
        await cur.execute("select original_name from tmdb_catalog where id = %s", (tv_id,))
        row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def _imdb_depuis_la_collecte(conn: psycopg.AsyncConnection, tv_id: int) -> str | None:
    """L'`imdb_id` de la fiche collectée. Il ouvre la seconde entrée Wikidata et
    surtout il **décide** de l'appariement TVmaze."""
    payload = await store.latest_payload(conn, source="tmdb", kind="tv", source_id=str(tv_id))
    return ((payload or {}).get("external_ids") or {}).get("imdb_id") or None


def _entier(valeur: Any) -> int | None:
    """`oeuvre.tvmaze_id` est un entier ; Wikidata le donne en chaîne."""
    try:
        return int(valeur) if valeur is not None else None
    except (TypeError, ValueError):
        return None


async def _noter(
    conn: psycopg.AsyncConnection,
    source: str,
    kind: str,
    source_id: str,
    resultat: FetchResult,
) -> None:
    """Note le passage dans `fetch_state` — et rien d'autre.

    Pour les réponses vides : « on a regardé, il n'y a rien » est une
    information d'état, pas du brut.
    """
    await store.mark_fetch(
        conn,
        source=source,
        kind=kind,
        source_id=source_id,
        http_status=resultat.status,
        changed=resultat.ok,
        error=resultat.error,
    )


async def _persist(
    conn: psycopg.AsyncConnection,
    source: str,
    kind: str,
    source_id: str,
    lang: str | None,
    resultat: FetchResult,
) -> None:
    """Le brut dans `raw_source` (R1), le passage dans `fetch_state`.

    La déduplication par empreinte fait qu'un contenu inchangé n'écrit rien —
    c'est elle qui tient la règle « jamais le même contenu deux fois » (R2).
    """
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
