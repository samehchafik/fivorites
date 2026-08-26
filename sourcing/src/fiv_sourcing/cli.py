"""Point d'entrée en ligne de commande."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from collections.abc import Callable, Coroutine
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import psycopg
import typer

if TYPE_CHECKING:
    from fiv_sourcing.sources.tmdb.backfill import BackfillReport
    from fiv_sourcing.sources.tmdb.export import ExportReport

from fiv_sourcing.config import VENDOR_DIR, Settings, get_settings
from fiv_sourcing.db import MigrationsNotFound, connect, migrate, pending_migrations, ping
from fiv_sourcing.http import FetcherStats
from fiv_sourcing.redact import SecretFilter, fingerprint, redact_dsn
from fiv_sourcing.univers import Univers, kinds_de, resoudre, resoudre_tmdb

app = typer.Typer(help="Acquisition de données Fivorites V2 — séries", no_args_is_help=True)
db_app = typer.Typer(help="Base de données", no_args_is_help=True)
tmdb_app = typer.Typer(help="Source TMDB", no_args_is_help=True)
crawl_app = typer.Typer(help="Le flux hors-TMDB", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(tmdb_app, name="tmdb")
app.add_typer(crawl_app, name="crawl")


@app.callback()
def _root(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretFilter())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        handlers=[handler],
    )

    # httpx journalise une ligne INFO par requête, URL complète comprise. Sur
    # une passe de plusieurs millions d'appels, c'est des gigaoctets de logs
    # pour aucune information — et, avec une clé v3, autant d'occasions de la
    # faire fuir. Le filtre ci-dessus la masquerait, mais le mieux reste de ne
    # pas l'écrire. À la demande avec --verbose.
    logging.getLogger("httpx").setLevel(logging.DEBUG if verbose else logging.WARNING)


@app.command()
def doctor() -> None:
    """Vérifie l'environnement : interpréteur vendorisé, base, identifiants."""
    settings = get_settings()
    ok = True

    version_py = sys.version.split()[0]
    if VENDOR_DIR.exists():
        # Poste local : l'interpréteur doit venir de vendor/, jamais du système.
        interpreter = Path(sys.executable).resolve()
        base = Path(sys.base_prefix).resolve()
        vendored = VENDOR_DIR in interpreter.parents or VENDOR_DIR in base.parents
        ok &= _line("interpréteur", vendored, f"{version_py} — {base}")
        if not vendored:
            typer.echo("        → Python hors vendor/. Relancer `make bootstrap`.")
    else:
        # Image Docker : pas de vendor/, la version est figée par le tag de base.
        _line("interpréteur", True, f"{version_py} — image, pas de vendor/")

    if not settings.has_tmdb_credentials:
        ok &= _line("identifiants TMDB", False, "aucun")
        typer.echo("        → renseigner TMDB_BEARER (token v4) dans .env")
    else:
        # L'empreinte permet de vérifier *quelle* clé est chargée — utile après
        # une rotation, ou pour distinguer deux environnements.
        secret = settings.tmdb_bearer or settings.tmdb_api_key
        kind = "token v4" if settings.tmdb_bearer else "clé v3"
        kind = f"{kind} {fingerprint(secret)}"
        # On demande son avis à TMDB : une variable non vide ne prouve rien.
        status = asyncio.run(_tmdb_check(settings))
        ok &= _line("identifiants TMDB", status == 200, f"{kind} — {_http_label(status)}")
        if status in (401, 403):
            typer.echo("        → jeton refusé par TMDB. Le token v4 est un JWT :")
            typer.echo("          il commence par `eyJ`, fait ~200 caractères et")
            typer.echo("          contient deux points. Une clé v3 (32 caractères")
            typer.echo("          hexadécimaux) va dans TMDB_API_KEY, pas TMDB_BEARER.")
        elif status != 200:
            typer.echo("        → TMDB injoignable, identifiants non vérifiés.")

    try:
        version, pending, tables = asyncio.run(
            _db_status(settings.database_url, settings.db_schema, settings.migrations_dir)
        )
    except Exception as exc:  # noqa: BLE001 — on veut le message brut
        ok &= _line("base", False, f"{type(exc).__name__}: {exc}")
        typer.echo("        → `make db-create` puis `make migrate`.")
    else:
        ok &= _line("base", True, version.split(",")[0])
        ok &= _line("migrations", not pending, "à jour" if not pending else f"{pending} en attente")
        ok &= _line("schéma", bool(tables), f"{settings.db_schema} — {tables} table(s)")

    raise typer.Exit(0 if ok else 1)


@db_app.command("migrate")
def db_migrate() -> None:
    """Applique les migrations manquantes."""
    settings = get_settings()

    # Dire où on écrit avant d'écrire : en conteneur, la cause d'un « rien ne
    # s'est passé » est presque toujours qu'on regarde une base et qu'on en
    # migre une autre.
    typer.echo(f"cible      : {redact_dsn(settings.database_url)} (schéma {settings.db_schema})")
    typer.echo(f"migrations : {settings.migrations_dir}")

    async def run() -> list[str]:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            return await migrate(conn, settings.migrations_dir)

    applied = _run_db(run)
    detail = f" : {', '.join(applied)}" if applied else " (base déjà à jour)"
    typer.echo(f"{len(applied)} migration(s) appliquée(s){detail}")


@tmdb_app.command("fetch")
def tmdb_fetch(
    ids: Annotated[list[int], typer.Option("--id", help="Id TMDB de l'œuvre (répétable)")],
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Collecte une ou plusieurs œuvres dans `raw_source`.

    ⚠️ L'univers n'est pas cosmétique : `--id 1399` désigne *Game of Thrones*
    en séries et un tout autre film en films. Se tromper d'univers collecte une
    œuvre parfaitement réelle, mais pas celle qu'on voulait.
    """
    from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher
    from fiv_sourcing.sources.tmdb.collect import collect

    settings = get_settings()
    monde = _univers(univers)
    if not settings.has_tmdb_credentials:
        typer.echo("Aucun identifiant TMDB. Renseigner TMDB_BEARER ou TMDB_API_KEY dans .env")
        raise typer.Exit(2)

    async def run() -> int:
        failures = 0
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            fetcher = build_fetcher(settings)
            async with fetcher:
                client = TmdbClient(fetcher, settings)
                for tv_id in ids:
                    report = await collect(conn, client, tv_id, monde)
                    marker = "ok " if report.ok else "ÉCHEC"
                    parties = f"{report.seasons_seen:>2} saisons  " if monde.parties else ""
                    typer.echo(
                        f"{marker} {tv_id:>8}  {report.requests:>3} requêtes  "
                        f"{parties}"
                        f"{report.rows_written:>3} ligne(s) écrite(s)"
                    )
                    for error in report.errors[:3]:
                        typer.echo(f"         {error}")
                    failures += int(not report.ok)
        return failures

    raise typer.Exit(1 if _run_db(run) else 0)


@app.command()
def enrich(
    ids: Annotated[
        list[int] | None,
        typer.Option(
            "--id", help="Une série précise (répétable). Défaut : toutes celles sans complément."
        ),
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Nombre de séries à traiter. Défaut : toutes.")
    ] = None,
    concurrency: Annotated[
        int, typer.Option("--concurrency", help="Séries traitées en parallèle.")
    ] = 4,
    order: Annotated[
        str,
        typer.Option(
            "--order",
            help="id (défaut), recent (année puis popularité), popularity, random.",
        ),
    ] = "id",
    refresh_after: Annotated[
        int | None,
        typer.Option("--refresh-after", help="Reprendre aussi celles vues il y a plus de N jours."),
    ] = None,
    univers_cle: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compter le reste à faire, sans rien télécharger.")
    ] = False,
) -> None:
    """Ajoute les sources tierces : Wikidata, Wikipédia, TVmaze.

    Sans `--id`, traite **toutes les œuvres collectées encore sans complément**
    et reprend là où la passe précédente s'est arrêtée. L'enrichissement se
    raccroche à la fiche collectée (`riche_source.raw_source_id`) : une œuvre
    doit être passée par `tmdb fetch` ou `tmdb backfill` d'abord.

    `--univers movies` enrichit les films. Trois choses changent, et rien
    d'autre : la propriété Wikidata d'entrée (`P4947` au lieu de `P4983` — les
    deux catalogues TMDB se numérotent indépendamment), l'absence de TVmaze qui
    est une base de séries, et le `kind` de reprise dans `fetch_state` pour que
    le film 550 et la série 550 ne se volent pas leur état de passage.

    Ce que l'enrichissement apporte à un film n'est pas la qualité de sa note
    mais son **existence** : un dossier sous 400 caractères n'est pas notable du
    tout, et l'article Wikipédia le fait passer le seuil. La couverture
    Wikipédia est d'ailleurs bien meilleure sur les films que sur les séries.
    """
    from fiv_sourcing import univers as mod_univers
    from fiv_sourcing.enrich import (
        EnrichAllReport,
        build_clients,
        build_fetcher,
        enrich_all,
        enrich_series,
        pending_ids,
    )

    settings = get_settings()
    langues = settings.wikipedia_languages
    try:
        univers = mod_univers.resoudre_tmdb(univers_cle)
    except ValueError as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc

    async def une_par_une() -> int:
        echecs = 0
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            fetcher = build_fetcher(settings)
            async with fetcher:
                clients = build_clients(fetcher)
                for tv_id in ids or []:
                    report = await enrich_series(
                        conn, clients, tv_id, languages=langues, univers=univers
                    )
                    marker = "ok " if report.sources else "rien"
                    typer.echo(
                        f"{marker} {tv_id:>8}  {report.requests:>2} requêtes  "
                        f"{report.rows_written:>2} ligne(s) riche(s)  "
                        f"{report.qid or '—':>10}  {', '.join(report.sources) or 'aucune source'}"
                    )
                    for erreur in report.errors[:3]:
                        typer.echo(f"           {erreur}")
                    echecs += int(not report.sources)
        return echecs

    started = time.monotonic()
    last_shown = 0.0

    def show(report: EnrichAllReport) -> None:
        nonlocal last_shown
        now = time.monotonic()
        if now - last_shown < 10 and report.remaining:
            return
        last_shown = now
        elapsed = now - started
        rate = report.done / elapsed if elapsed else 0
        eta = report.remaining / rate if rate else 0
        typer.echo(
            f"{report.done:>7}/{report.selected}  "
            f"{report.resolved} raccordée(s)  {report.enriched} enrichie(s)  "
            f"{rate:5.2f} {univers.libelle}/s  reste {_duree(eta)}"
        )

    async def en_masse() -> EnrichAllReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            selection = await pending_ids(
                conn, refresh_after=refresh_after, limit=limit, order=order, univers=univers
            )
            if dry_run or not selection:
                return EnrichAllReport(selected=len(selection))

            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signame in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signame, _request_stop, stop)

            fetcher = build_fetcher(settings)
            async with fetcher:
                resultat = await enrich_all(
                    conn,
                    build_clients(fetcher),
                    selection,
                    languages=langues,
                    concurrency=concurrency,
                    stop=stop,
                    on_progress=show,
                    univers=univers,
                )
                stats.append(fetcher.stats)
                return resultat

    typer.echo(
        f"univers : {univers.cle} (Wikidata {univers.wikidata_propriete}"
        f"{', TVmaze' if univers.tvmaze else ', sans TVmaze'})"
    )
    typer.echo(f"langues : {', '.join(langues)}")
    typer.echo(f"débit   : {settings.enrich_rate_limit} req/s Wikimedia (ENRICH_RATE_LIMIT)")
    typer.echo(f"          {settings.tvmaze_rate_limit} req/s TVmaze (TVMAZE_RATE_LIMIT)")
    stats: list[FetcherStats] = []

    if ids:
        raise typer.Exit(1 if _run_db(une_par_une) == len(ids) else 0)

    report = _run_db(en_masse)
    if dry_run:
        typer.echo(f"à enrichir : {report.selected} série(s)")
        return
    if not report.selected:
        typer.echo("Rien à enrichir. La sélection ne porte que sur les séries déjà")
        typer.echo("collectées : `tmdb backfill` d'abord si la collecte n'a pas tourné.")
        return

    typer.echo("")
    typer.echo(f"traitées      : {report.done}/{report.selected}")
    typer.echo(f"raccordées    : {report.resolved}  (item Wikidata)")
    typer.echo(f"enrichies     : {report.enriched}  (au moins une source)")
    typer.echo(f"requêtes      : {report.requests}")
    typer.echo(f"lignes riches : {report.rows_written}")
    if report.errors:
        typer.echo(f"erreurs       : {report.errors}")

    # Même raisonnement que pour TMDB : le plafond se règle sur ce qu'une passe
    # réelle a déclenché, pas sur une valeur choisie a priori.
    if stats:
        _bilan_debit(stats[0], settings.enrich_rate_limit, variable="ENRICH_RATE_LIMIT")

    if report.interrupted:
        typer.echo("")
        typer.echo("Interrompu. Relancer la même commande reprend où on s'est arrêté.")


@app.command()
def videos(
    ids: Annotated[
        list[int] | None,
        typer.Option("--id", help="Une série précise (répétable). Défaut : celles non examinées."),
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Nombre de séries à traiter. Défaut : toutes.")
    ] = None,
    order: Annotated[
        str, typer.Option("--order", help="popularity (défaut), id, recent, random.")
    ] = "popularity",
    tout: Annotated[
        bool, typer.Option("--tout", help="Reprendre aussi les séries déjà examinées.")
    ] = False,
    sans_saisons: Annotated[
        bool, typer.Option("--sans-saisons", help="Ne lire que la fiche série, pas les saisons.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compter le reste à faire, sans rien écrire.")
    ] = False,
) -> None:
    """Projette les bandes-annonces du brut TMDB vers `video`.

    Aucun appel réseau, aucun quota : TMDB sert déjà les vidéos dans le payload
    des séries et des saisons, cette passe ne fait que les rendre
    interrogeables. Une série doit donc être passée par `tmdb fetch` d'abord.

    Les séries sans aucune vidéo sont marquées examinées elles aussi — sans
    quoi chaque passe rouvrirait indéfiniment les mêmes fiches vides.
    """
    from fiv_sourcing import video as canal

    settings = get_settings()

    async def run() -> tuple[int, int, dict[str, int]]:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            cibles = (
                list(ids)
                if ids
                else await canal.series_a_projeter(conn, limit=limit, order=order, tout=tout)
            )
            if dry_run:
                return len(cibles), 0, await canal.bilan(conn)

            trouvees = 0
            for numero, id_tmdb in enumerate(cibles, 1):
                trouvees += await canal.projeter_serie(conn, id_tmdb, saisons=not sans_saisons)
                if numero % 500 == 0:
                    typer.echo(f"  {numero}/{len(cibles)} séries · {trouvees} vidéos")
            return len(cibles), trouvees, await canal.bilan(conn)

    try:
        cibles, trouvees, etat = _run_db(run)
    except ValueError as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc

    if dry_run:
        typer.echo(f"à examiner : {cibles} série(s)")
    else:
        typer.echo(f"séries examinées : {cibles}")
        typer.echo(f"vidéos retenues  : {trouvees}")
    typer.echo("")
    _etat_video(etat)


def _etat_video(etat: dict[str, int]) -> None:
    typer.echo(f"total examiné        : {etat['examinees']:>8}")
    typer.echo(f"dont avec vidéo      : {etat['avec_video']:>8}")
    typer.echo(f"vidéos en base       : {etat['videos']:>8}")
    typer.echo(f"annonces officielles : {etat['annonces_officielles']:>8}")
    typer.echo(f"séries avec du fr    : {etat['series_en_francais']:>8}")
    typer.echo(f"jamais vérifiées     : {etat['jamais_verifiees']:>8}")
    typer.echo(f"mortes               : {etat['mortes']:>8}")


@app.command("rss-add")
def rss_add(
    url: Annotated[str, typer.Argument(help="L'URL du flux RSS ou Atom.")],
    editeur: Annotated[str, typer.Option("--editeur", help="'telerama', 'variety'…")],
    univers: Annotated[
        list[str] | None,
        typer.Option("--univers", help="Univers concernés (répétable). Défaut : tous."),
    ] = None,
) -> None:
    """Ajoute un flux au registre — après l'avoir sondé.

    La sonde n'est pas du zèle : les URLs de flux périment, et un flux mort
    inscrit sans vérification échouerait en silence à chaque passage horaire.
    Ici il échoue tout de suite, devant celui qui peut corriger l'URL.

    Le registre vit en base (`rss_feed`) : ajouter un flux est ce geste-ci ou
    une ligne SQL, jamais un déploiement.
    """
    from fiv_sourcing.enrich import build_fetcher
    from fiv_sourcing.sources import rss

    settings = get_settings()
    for u in univers or []:
        if u not in ("series", "movies", "livres"):
            typer.echo(f"ERREUR : univers inconnu : {u}")
            raise typer.Exit(1)

    async def run() -> int:
        fetcher = build_fetcher(settings)
        async with fetcher:
            statut, corps, _, _ = await fetcher.get_conditional_text(url)
        if statut < 200 or statut >= 300 or not corps:
            typer.echo(f"ERREUR : le flux répond {statut or 'rien'} — non inscrit.")
            raise typer.Exit(1)
        items = rss.parser_flux(corps)
        if not items:
            typer.echo("ERreur : la réponse ne contient aucun item lisible — non inscrit.")
            raise typer.Exit(1)

        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    insert into rss_feed (url, editeur, univers) values (%s, %s, %s)
                    on conflict (url) do update set editeur = excluded.editeur,
                        univers = excluded.univers, actif = true
                    returning id
                    """,
                    (url, editeur, univers or None),
                )
                feed_id = (await cur.fetchone())[0]
        typer.echo(f"flux #{feed_id} inscrit — {len(items)} item(s) lisibles au sondage.")
        typer.echo(f"  dernier : {items[0]['title'][:70]}")
        return 0

    _run_db(run)


@app.command("rss-list")
def rss_list() -> None:
    """Le registre des flux, avec l'état du dernier passage."""
    settings = get_settings()

    async def run():
        async with (
            connect(settings.database_url, schema=settings.db_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                select f.id, f.editeur, f.actif, f.last_status, f.last_success_at,
                       f.last_error, f.url,
                       (select count(*) from raw_rss_item i where i.feed_id = f.id)
                from rss_feed f order by f.id
                """
            )
            return await cur.fetchall()

    lignes = _run_db(run)
    if not lignes:
        typer.echo("aucun flux inscrit — `rss-add <url> --editeur <nom>` pour commencer.")
        return
    for fid, editeur, actif, statut, succes, erreur, url, items in lignes:
        etat = "·" if actif else "⏸"
        quand = f"{succes:%d/%m %H:%M}" if succes else "jamais"
        typer.echo(
            f"{etat} #{fid:<3} {editeur:<14} {statut or '—':>4}  {quand:>12}"
            f"  {items:>5} item(s)  {url[:60]}"
        )
        if erreur:
            typer.echo(f"        ⚠ {erreur}")


@app.command("rss-sweep")
def rss_sweep() -> None:
    """Un passage sur tous les flux actifs — collecte brute, aucune dérivation.

    En rythme de croisière, la réponse dominante est le 304 : le GET est
    conditionnel, et un flux inchangé coûte quelques octets. C'est ce qui rend
    le passage horaire défendable vis-à-vis des éditeurs.

    La liaison aux œuvres et le typage sont une autre commande
    (`actualite-derive`, étape suivante de l'architecture) : collecter et
    interpréter dans le même geste est exactement ce que ce pipeline s'interdit.
    """
    from fiv_sourcing.actualite import balayer_flux
    from fiv_sourcing.enrich import build_fetcher

    settings = get_settings()

    async def run():
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            fetcher = build_fetcher(settings)
            async with fetcher:
                return await balayer_flux(conn, fetcher)

    report = _run_db(run)
    typer.echo(
        f"flux visités  : {report.flux}"
        f"\ninchangés     : {report.inchanges}  (304 — le passage normal)"
        f"\nitems vus     : {report.items_vus}"
        f"\nnouveaux      : {report.items_nouveaux}"
        f"\nerreurs       : {report.erreurs}"
    )
    if not report.flux:
        typer.echo("aucun flux actif — `rss-add` d'abord.")


@app.command("actualite-derive")
def actualite_derive(
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Plafond de lignes de brut examinées. Défaut : tout."),
    ] = None,
) -> None:
    """Dérive l'actualité des fiches recollectées — les « news TMDB », gratuites.

    `raw_source` ne grandit que quand le contenu change : toute nouvelle ligne
    de fiche est un changement réel, et la comparer à la précédente dit ce qui
    est arrivé à l'œuvre — saison annoncée, date de diffusion, statut, sortie.
    Aucun réseau, aucun appel payant.

    La reprise est un entier (`actualite_curseur`) : relancer continue, une
    interruption ne coûte que le lot en cours, et remettre le curseur à zéro
    rejoue tout — le rejeu est idempotent, les clés naturelles font qu'un
    événement déjà dérivé ne se réécrit pas.

    Sa place est dans `nightly.sh`, après `backfill` : c'est lui qui fait
    grossir le brut, donc c'est sa fin qui rend les diffs disponibles.
    """
    from fiv_sourcing.actualite import deriver_diffs

    settings = get_settings()

    async def run():
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            return await deriver_diffs(conn, limit=limit)

    report = _run_db(run)
    typer.echo(
        f"examinées      : {report.examines} ligne(s) de brut"
        f"\npremières      : {report.sans_precedent}  (pas de version précédente, rien à dire)"
        f"\névénements     : {report.evenements}"
    )
    for type_evt, n in sorted(report.par_type.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {type_evt:<20} {n}")
    if not report.evenements and report.examines:
        typer.echo("aucun événement — les recollectes n'ont rien changé d'annonçable.")


@app.command("videos-check")
def videos_check(
    limit: Annotated[
        int | None, typer.Option("--limit", help="Nombre de vidéos à vérifier. Défaut : toutes.")
    ] = None,
    age: Annotated[
        int | None,
        typer.Option("--age", help="Ne revérifier que les vidéos vues il y a plus de N jours."),
    ] = 30,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compter le reste à faire, sans rien vérifier.")
    ] = False,
) -> None:
    """Vérifie que les vidéos sont encore lisibles chez leur hébergeur.

    Une clé YouTube n'est pas stable : la vidéo est retirée pour droits, passée
    en privée à la fin d'une campagne, ou la chaîne disparaît. Rien ne nous en
    avertit, et la fiche propose alors un lecteur mort.

    Le contrôle passe par les points oEmbed publics — pas de clé, pas de quota
    déclaré, et un 200 qui signifie exactement « lisible publiquement ». Les
    vidéos mortes sont **marquées, jamais supprimées** : la re-projection
    depuis le brut les recréerait, et une vidéo privée redevient parfois
    publique.

    Prévue pour tourner régulièrement — `--age 30` ne rouvre que ce qui n'a pas
    été vu depuis un mois, en commençant toujours par les jamais-vérifiées.
    """
    from fiv_sourcing import video as canal
    from fiv_sourcing.enrich import build_fetcher

    settings = get_settings()

    async def run() -> tuple[int, int, int, int, dict[str, int]]:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            cibles = await canal.videos_a_verifier(conn, limit=limit, age_jours=age)
            if dry_run:
                return len(cibles), 0, 0, 0, await canal.bilan(conn)

            vivantes = mortes = reportees = 0
            fetcher = build_fetcher(settings)
            async with fetcher:
                for numero, (oeuvre_id, site, cle) in enumerate(cibles, 1):
                    try:
                        ok, statut = await canal.verifier_une(fetcher, site, cle)
                    except canal.IndisponibleTemporairement:
                        # Ni vivante ni morte : on ne touche pas à la ligne,
                        # sinon un hébergeur momentanément indisponible ferait
                        # disparaître tout le catalogue d'un coup.
                        reportees += 1
                        continue
                    await canal.marquer(conn, oeuvre_id, site, cle, vivante=ok, statut=statut)
                    vivantes, mortes = vivantes + ok, mortes + (not ok)
                    if numero % 500 == 0:
                        typer.echo(f"  {numero}/{len(cibles)} · {mortes} morte(s)")
            return len(cibles), vivantes, mortes, reportees, await canal.bilan(conn)

    cibles, vivantes, mortes, reportees, etat = _run_db(run)

    if dry_run:
        typer.echo(f"à vérifier : {cibles} vidéo(s)")
    else:
        typer.echo(f"vérifiées : {cibles}")
        typer.echo(f"  vivantes : {vivantes}")
        typer.echo(f"  mortes   : {mortes}")
        if reportees:
            typer.echo(f"  reportées: {reportees}  (hébergeur injoignable — rien conclu)")
    typer.echo("")
    _etat_video(etat)


@crawl_app.command("wikidata")
def crawl_wikidata_cmd(
    univers_cle: Annotated[
        str,
        typer.Option(
            "--univers",
            help="series (défaut) ou livres. Les livres n'ont pas de TMDB : "
            "ce crawler est leur flux principal.",
        ),
    ] = "series",
    langue: Annotated[
        str | None,
        typer.Option(
            "--langue",
            help="Code de langue originale (P364 séries, P407 livres), ex. ar, fr.",
        ),
    ] = None,
    avec_imdb: Annotated[
        bool,
        typer.Option(
            "--avec-imdb",
            help="Inclure les items à imdb_id — probablement des séries TMDB non "
            "reliées, que le flux 1 rattrape déjà. Risque de doublons, assumé.",
        ),
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Nombre d'items à traiter. Défaut : tous.")
    ] = None,
    concurrency: Annotated[
        int, typer.Option("--concurrency", help="Items traités en parallèle.")
    ] = 4,
    min_sitelinks: Annotated[
        int,
        typer.Option(
            "--min-sitelinks",
            help="Livres seulement : plancher de notoriété du balayage. En "
            "dessous, l'item est un article unique dans une seule langue, "
            "sans matière à notation.",
        ),
    ] = 5,
    refaire: Annotated[
        bool,
        typer.Option(
            "--refaire",
            help="Rejouer les œuvres déjà collectées au lieu de les sauter. "
            "À utiliser quand la collecte a appris à extraire un fait de plus.",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compter le reste à faire, sans rien écrire.")
    ] = False,
) -> None:
    """Les œuvres qui entrent par Wikidata, pas par TMDB.

    Séries : balaye les items « série télévisée » sans identifiant TMDB — par
    défaut le **noyau dur**, sans imdb_id non plus : injoignable par tout
    autre chemin. Crée l'œuvre par QID (id_tmdb null), conserve le brut,
    enrichit via Wikipédia et TVmaze.

    Livres (`--univers livres`) : balaye les œuvres littéraires par notoriété
    décroissante, crée l'œuvre par QID, enrichit via Wikipédia et Open
    Library (éditions, traductions).

    Reprenable dans les deux cas : les items déjà regardés sont sautés.
    """
    from fiv_sourcing.crawl import CrawlReport, crawl_wikidata, deja_regardes, sweep
    from fiv_sourcing.enrich import build_clients, build_fetcher

    settings = get_settings()
    monde = _univers_crawl(univers_cle)
    if monde.openlibrary and not langue:
        # Le balayage toutes langues fait trier tous les items « œuvre
        # littéraire » par WDQS, qui coupe avant la première page (mesuré).
        # La collecte livres se pense par langue cible de toute façon.
        typer.echo("ERREUR : --langue est requis pour les livres (fr, en, es, ar…)")
        raise typer.Exit(2)
    if monde.openlibrary and settings.http_timeout < 65:
        # La première page à froid d'un corpus riche frôle 35 s ; WDQS coupe
        # à 60 s. On s'aligne sur son couperet plutôt que d'abandonner avant.
        settings = settings.model_copy(update={"http_timeout": 65.0})
    langues = settings.wikipedia_languages

    started = time.monotonic()
    last_shown = 0.0

    def show(report: CrawlReport) -> None:
        nonlocal last_shown
        now = time.monotonic()
        if now - last_shown < 10 and report.remaining:
            return
        last_shown = now
        elapsed = now - started
        rate = report.done / elapsed if elapsed else 0
        eta = report.remaining / rate if rate else 0
        typer.echo(
            f"{report.done:>7}/{report.selected}  "
            f"{report.enriched} enrichie(s)  {rate:5.2f} item/s  reste {_duree(eta)}"
        )

    async def run() -> CrawlReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            report = CrawlReport()
            fetcher = build_fetcher(settings)
            async with fetcher:
                clients = build_clients(fetcher)
                items = await sweep(
                    clients,
                    report,
                    univers=monde,
                    langue=langue,
                    avec_imdb=avec_imdb,
                    sitelinks_min=min_sitelinks,
                    max_items=None,
                )
                # R4 : rejouer l'enrichissement, c'est réinterroger. Quand
                # l'extraction apprend un fait de plus — les genres, les
                # couvertures — les œuvres déjà collectées ne l'ont pas, et
                # seule une nouvelle interrogation le leur donne.
                # `upsert_riche_source` remplace la ligne au lieu d'en créer
                # une seconde : rejouer ne duplique rien.
                vus = (
                    set()
                    if refaire
                    else await deja_regardes(
                        conn, [i["qid"] for i in items], kind=monde.lookup_kind
                    )
                )
                restants = [i for i in items if i["qid"] not in vus]
                if limit is not None:
                    restants = restants[:limit]
                if dry_run:
                    report.selected = len(restants)
                    return report

                stop = asyncio.Event()
                loop = asyncio.get_running_loop()
                for signame in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(signame, _request_stop, stop)

                return await crawl_wikidata(
                    conn,
                    clients,
                    restants,
                    univers=monde,
                    languages=langues,
                    concurrency=concurrency,
                    stop=stop,
                    on_progress=show,
                    report=report,
                )

    perimetre = f"langue={langue}" if langue else "toutes langues"
    if refaire:
        perimetre += ", en rejouant le déjà-vu"
    if monde.openlibrary:
        perimetre += f", sitelinks >= {min_sitelinks}"
        typer.echo(f"périmètre : œuvres littéraires par notoriété — {perimetre}")
    else:
        perimetre += ", avec imdb" if avec_imdb else ", sans imdb (noyau dur)"
        typer.echo(f"périmètre : items série sans id TMDB — {perimetre}")
    typer.echo(f"langues d'articles : {', '.join(langues)}")

    report = _run_db(run)
    if dry_run:
        typer.echo(f"balayés : {report.swept}  à traiter : {report.selected}")
        return

    typer.echo("")
    typer.echo(f"balayés       : {report.swept}")
    typer.echo(f"traités       : {report.done}/{report.selected}")
    typer.echo(f"enrichis      : {report.enriched}  (au moins une source)")
    typer.echo(f"requêtes      : {report.requests}")
    typer.echo(f"lignes riches : {report.rows_written}")
    if report.errors:
        typer.echo(f"erreurs       : {report.errors}")
    if report.interrupted:
        typer.echo("")
        typer.echo("Interrompu. Relancer la même commande reprend où on s'est arrêté.")
    return report


# Le plancher de notoriété du balayage, langue par langue.
#
# Le classement par notoriété se fait chez nous (voir `SWEEP_LIVRES`), ce qui
# oblige à balayer tout le périmètre avant de collecter : plus le plancher est
# bas, plus le balayage est long et plus il expose aux refus de WDQS.
#
# Mesuré le 2026-08-21, à 5 sitelinks et plus : fr 1 193 œuvres, es 325,
# ar 220 — trois balayages qui passent. L'anglais en compte ~3 500 et échoue
# en fin de course (502, puis 429). À 15, il en ramène 1 370 et termine
# proprement — c'est aussi un meilleur périmètre : en dessous, l'item est
# souvent un article unique dans une seule langue, sans matière à notation.
PLANCHER_PAR_LANGUE: dict[str, int] = {"en": 15}
PLANCHER_DEFAUT = 5


@crawl_app.command("livres")
def crawl_livres_cmd(
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Nombre d'items par langue. Défaut : tous."),
    ] = None,
    min_sitelinks: Annotated[
        int | None,
        typer.Option(
            "--min-sitelinks",
            help="Plancher de notoriété, pour TOUTES les langues. Par défaut, "
            "chacune a le sien : 15 en anglais, 5 ailleurs.",
        ),
    ] = None,
    concurrency: Annotated[
        int, typer.Option("--concurrency", help="Items traités en parallèle.")
    ] = 4,
    refaire: Annotated[
        bool,
        typer.Option(
            "--refaire",
            help="Rejouer les livres déjà collectés — quand la collecte a "
            "appris à extraire un fait de plus (genres, couvertures…).",
        ),
    ] = False,
) -> None:
    """Les quatre langues cibles, l'une après l'autre : fr, en, es, ar.

    Un raccourci sur `crawl wikidata --univers livres --langue <l>` — même
    reprise (le déjà-vu se saute), mêmes limiteurs. Interrompre puis relancer
    reprend où on s'est arrêté, langue par langue.

    Le plancher de notoriété est **propre à chaque langue** (voir
    `PLANCHER_PAR_LANGUE`) : l'anglais a un corpus trop large pour être
    balayé en entier. `--min-sitelinks` impose la même valeur partout.

    Le récapitulatif final n'est pas décoratif : WDQS est un service gratuit
    et partagé qui refuse parfois une page de balayage. Une langue qui échoue
    doit se voir — sinon on la croit collectée, et rien ne le dira jamais.
    """
    bilan: list[tuple[str, int, int, int]] = []
    for langue in ("fr", "en", "es", "ar"):
        plancher = (
            min_sitelinks
            if min_sitelinks is not None
            else PLANCHER_PAR_LANGUE.get(langue, PLANCHER_DEFAUT)
        )
        typer.echo(f"\n=== {langue} (sitelinks >= {plancher}) ===")
        report = crawl_wikidata_cmd(
            univers_cle="livres",
            langue=langue,
            avec_imdb=False,
            limit=limit,
            concurrency=concurrency,
            min_sitelinks=plancher,
            refaire=refaire,
            dry_run=False,
        )
        bilan.append((langue, report.swept, report.enriched, report.errors))

    typer.echo("")
    typer.echo("=== bilan ===")
    for langue, balayes, enrichis, erreurs in bilan:
        etat = f"{erreurs} erreur(s)" if erreurs else "ok"
        typer.echo(f"{langue} : {balayes:>6} balayé(s), {enrichis:>5} enrichi(s) — {etat}")
    fautives = [langue for langue, balayes, _, erreurs in bilan if erreurs or not balayes]
    if fautives:
        typer.echo("")
        typer.echo(
            f"⚠ à relancer : {', '.join(fautives)} — le balayage n'a pas abouti, "
            "le classement par notoriété y est donc incomplet."
        )


@tmdb_app.command("export")
def tmdb_export(
    day: Annotated[
        str | None,
        typer.Option(
            "--date", help="Export d'un jour donné (AAAA-MM-JJ). Défaut : le plus récent."
        ),
    ] = None,
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Récupère la liste de toutes les œuvres depuis l'export quotidien TMDB.

    Fichier public, aucune clé d'API requise, aucun quota consommé. Deux
    fichiers distincts, un par univers : `tv_series_ids` et `movie_ids`.
    """
    from fiv_sourcing.sources.tmdb.client import build_public_fetcher
    from fiv_sourcing.sources.tmdb.export import ExportUnavailable, refresh_catalog

    settings = get_settings()
    wanted = date.fromisoformat(day) if day else None
    monde = _univers(univers)

    async def run() -> ExportReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            fetcher = build_public_fetcher(settings)
            async with fetcher:
                return await refresh_catalog(conn, fetcher, wanted, monde)

    try:
        report = _run_db(run)
    except ExportUnavailable as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc

    typer.echo(f"export       : {report.url}")
    typer.echo(f"date         : {report.exported_on}")
    typer.echo(f"lues         : {report.series_read:>9,}".replace(",", " "))
    typer.echo(f"nouvelles    : {report.inserted:>9,}".replace(",", " "))
    typer.echo(f"mises à jour : {report.updated:>9,}".replace(",", " "))


@tmdb_app.command("dates")
def tmdb_dates(
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Recopie les dates de diffusion du brut vers l'inventaire.

    Sans réseau. C'est ce qui alimente `--order recent` : la date vit dans le
    payload de la fiche, et trier 228 000 séries dessus décompresserait toute la
    table à chaque passe. À relancer après chaque collecte — une série
    fraîchement téléchargée n'a sa date ici qu'après ce passage.
    """
    from fiv_sourcing.sources.tmdb.export import refresh_air_dates

    settings = get_settings()

    async def run() -> tuple[int, int, int]:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            majs = await refresh_air_dates(conn, _univers(univers))
            async with conn.cursor() as cur:
                await cur.execute(
                    "select count(*) filter (where first_air_date is not null), count(*) "
                    "from tmdb_catalog where univers = %s",
                    (_univers(univers).cle,),
                )
                datees, total = await cur.fetchone()
            return majs, datees, total

    majs, datees, total = _run_db(run)
    espace = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731
    typer.echo(f"mises à jour : {espace(majs)}")
    typer.echo(f"datées       : {espace(datees)} / {espace(total)}")
    if datees < total:
        typer.echo(f"               {espace(total - datees)} sans date — pas encore collectées")


@tmdb_app.command("changes")
def tmdb_changes(
    days: Annotated[int, typer.Option("--days", help="Fenêtre en jours. TMDB plafonne à 14.")] = 1,
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Marque les œuvres que TMDB signale comme modifiées.

    Ne collecte rien : pose une marque que `backfill` transformera en
    recollecte. Si cette commande échoue à mi-parcours, ce qu'elle a déjà
    marqué reste acquis.
    """
    from fiv_sourcing.sources.tmdb.changes import ChangesReport, refresh_changes
    from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher

    settings = get_settings()
    if not settings.has_tmdb_credentials:
        typer.echo("Aucun identifiant TMDB. Renseigner TMDB_BEARER ou TMDB_API_KEY dans .env")
        raise typer.Exit(2)

    async def run() -> ChangesReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            fetcher = build_fetcher(settings)
            async with fetcher:
                return await refresh_changes(
                    conn, TmdbClient(fetcher, settings), days=days, univers=_univers(univers)
                )

    report = _run_db(run)

    typer.echo(f"fenêtre        : {report.start} → {report.end} ({report.pages} page(s))")
    typer.echo(f"modifiées      : {report.ids_seen}")
    typer.echo(f"marquées       : {report.marked}")
    if report.unknown:
        typer.echo(f"inconnues      : {report.unknown}  (pas encore dans le catalogue)")
        typer.echo("                 → `tmdb export` les fera entrer")
    if report.truncated:
        typer.echo("")
        typer.echo("Réponse tronquée : trop de pages. Réduire --days.")
    typer.echo("")
    typer.echo("`tmdb backfill` recollectera les œuvres marquées.")


@tmdb_app.command("backfill")
def tmdb_backfill(
    limit: Annotated[
        int | None, typer.Option("--limit", help="Nombre de séries à traiter. Défaut : toutes.")
    ] = None,
    concurrency: Annotated[
        int, typer.Option("--concurrency", help="Séries traitées en parallèle.")
    ] = 4,
    order: Annotated[
        str,
        typer.Option(
            "--order",
            help="id (neutre, défaut), random (pour estimer une durée) ou popularity.",
        ),
    ] = "id",
    refresh_after: Annotated[
        int | None,
        typer.Option(
            "--refresh-after", help="Reprendre aussi les séries collectées il y a plus de N jours."
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compter le reste à faire, sans rien collecter.")
    ] = False,
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Collecte tout le catalogue. Reprend là où la passe précédente s'est arrêtée.

    Aucun filtre : ce qui mérite d'être montré se décide en aval, sur des
    données complètes.
    """
    from fiv_sourcing.sources.tmdb.backfill import BackfillReport, backfill, pending_ids
    from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher

    settings = get_settings()
    monde = _univers(univers)
    if not settings.has_tmdb_credentials and not dry_run:
        typer.echo("Aucun identifiant TMDB. Renseigner TMDB_BEARER ou TMDB_API_KEY dans .env")
        raise typer.Exit(2)

    started = time.monotonic()
    last_shown = 0.0

    def show(report: BackfillReport) -> None:
        nonlocal last_shown
        now = time.monotonic()
        # Une ligne toutes les 10 s, plus la dernière : sur 228 000 séries, un
        # affichage par unité noierait les avertissements réellement utiles.
        if now - last_shown < 10 and report.remaining:
            return
        last_shown = now
        elapsed = now - started
        rate = report.done / elapsed if elapsed else 0
        eta = report.remaining / rate if rate else 0
        typer.echo(
            f"{report.done:>7}/{report.selected}  "
            f"{report.ok} ok  {report.failed} échec(s)  "
            f"{rate:5.2f} {monde.libelle}/s  reste {_duree(eta)}"
        )

    async def run() -> BackfillReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            ids = await pending_ids(
                conn, refresh_after=refresh_after, limit=limit, order=order, univers=monde
            )
            if dry_run or not ids:
                return BackfillReport(selected=len(ids))

            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signame in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signame, _request_stop, stop)

            fetcher = build_fetcher(settings)
            async with fetcher:
                report = await backfill(
                    conn,
                    TmdbClient(fetcher, settings),
                    ids,
                    concurrency=concurrency,
                    stop=stop,
                    on_progress=show,
                    univers=monde,
                )
                stats.append(fetcher.stats)
                return report

    if monde.parties:
        typer.echo(f"langues : {', '.join(settings.season_languages)}")
    else:
        # Le rappel qui évite de croire à une passe incomplète : un film ne
        # coûte qu'un appel, la collecte va donc quarante fois plus vite qu'à
        # nombre d'œuvres égal côté séries.
        typer.echo("langues : sans objet — un film tient en un appel")
    typer.echo(f"débit   : {settings.tmdb_rate_limit} requête/s (TMDB_RATE_LIMIT)")
    stats: list[FetcherStats] = []
    report = _run_db(run)

    if dry_run:
        typer.echo(f"à collecter : {report.selected} {monde.libelle}(s)")
        return
    if not report.selected:
        typer.echo("Rien à collecter. Lancer `tmdb export` si le catalogue est vide.")
        return

    typer.echo("")
    typer.echo(f"traitées      : {report.done}/{report.selected}")
    typer.echo(f"réussies      : {report.ok}")
    typer.echo(f"en échec      : {report.failed}")
    typer.echo(f"requêtes      : {report.requests}")
    typer.echo(f"lignes brutes : {report.rows_written}")

    if stats:
        _bilan_debit(stats[0], settings.tmdb_rate_limit)

    if report.interrupted:
        typer.echo("")
        typer.echo(f"Interrompu — {report.remaining} {monde.libelle}(s) restant(s).")
        typer.echo("Relancer la même commande reprend où on s'est arrêté.")
        raise typer.Exit(130)


def _bilan_debit(
    stats: FetcherStats, rate_limit: float, *, variable: str = "TMDB_RATE_LIMIT"
) -> None:
    """Ce que la passe apprend sur le plafond réellement toléré.

    Pour TMDB, leur limite dure a été supprimée en 2019 et ce qui subsiste n'est
    pas documenté. Pour les sources tierces, seule TVmaze annonce un chiffre.
    Dans les deux cas, plutôt que de régler le débit sur une valeur trouvée dans
    un forum, on regarde combien de 429 une passe réelle a déclenchés.
    """
    typer.echo("")
    typer.echo(f"requêtes HTTP : {stats.requests}  (dont {stats.retries} reprise(s))")
    typer.echo(f"429 reçus     : {stats.rate_limited}")
    if stats.transport_errors:
        typer.echo(f"erreurs réseau: {stats.transport_errors}")

    if not stats.rate_limited:
        typer.echo(
            f"              → aucun bridage à {rate_limit} req/s. "
            f"Monter {variable} accélérerait la passe."
        )
    elif stats.rate_limited_ratio > 0.01:
        typer.echo(
            f"              → {stats.rate_limited_ratio:.1%} des requêtes bridées. "
            f"Baisser {variable} : les reprises coûtent plus qu'elles ne rapportent."
        )
    else:
        typer.echo("              → bridage marginal, le débit actuel est proche du plafond.")


def _request_stop(stop: asyncio.Event) -> None:
    if not stop.is_set():
        typer.echo("\nArrêt demandé — on termine les collectes en cours…")
        stop.set()


def _duree(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    heures, reste = divmod(int(seconds), 3600)
    minutes, secondes = divmod(reste, 60)
    if heures:
        return f"{heures} h {minutes:02d}"
    if minutes:
        return f"{minutes} min {secondes:02d}"
    return f"{secondes} s"


@tmdb_app.command("catalog")
def tmdb_catalog(
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Volumétrie de l'inventaire et répartition par popularité."""
    settings = get_settings()
    monde = _univers(univers)

    async def run() -> tuple[tuple, list[tuple]]:
        async with (
            connect(settings.database_url, schema=settings.db_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                select count(*), count(*) filter (where adult),
                       max(exported_on), count(*) filter (where exported_on < (
                           select max(exported_on) from tmdb_catalog
                           where univers = %(univers)s))
                from tmdb_catalog where univers = %(univers)s
                """,
                {"univers": monde.cle},
            )
            resume = await cur.fetchone()

            # Déciles de popularité : c'est la stratification sur laquelle
            # reposera l'échantillon, et la courbe qui dira où s'arrête le
            # périmètre notable.
            await cur.execute(
                """
                select decile, count(*), max(popularity), min(popularity)
                from (
                    select popularity,
                           ntile(10) over (order by popularity desc) as decile
                    from tmdb_catalog where univers = %(univers)s
                ) t
                group by decile order by decile
                """,
                {"univers": monde.cle},
            )
            return resume, await cur.fetchall()

    (total, adultes, dernier_export, disparues), deciles = _run_db(run)

    if not total:
        typer.echo(f"Inventaire vide. Lancer `tmdb export --univers {monde.cle}` d'abord.")
        raise typer.Exit(1)

    espace = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731
    typer.echo(f"univers         : {monde.cle}")
    typer.echo(f"œuvres          : {espace(total)}")
    typer.echo(f"dont adulte     : {espace(adultes)}")
    typer.echo(f"dernier export  : {dernier_export}")
    typer.echo(f"absentes depuis : {espace(disparues)}  (supprimées de TMDB)")
    typer.echo("")
    typer.echo(f"{'décile':<8}{'œuvres':>10}{'popularité max':>16}{'min':>12}")
    for decile, nombre, maxi, mini in deciles:
        typer.echo(f"{decile:<8}{espace(nombre):>10}{maxi:>16.2f}{mini:>12.2f}")


@tmdb_app.command("stats")
def tmdb_stats(
    univers: Annotated[
        str, typer.Option("--univers", help="series (défaut) ou movies.")
    ] = "series",
) -> None:
    """Ce qu'il y a en base, par type d'objet.

    Le tableau du haut couvre **tous** les univers — c'est la question « qu'y
    a-t-il en base », et un `kind` par ligne y répond directement. La
    projection de volume, elle, porte sur l'univers demandé : extrapoler la
    taille d'un film depuis des séries donnerait un chiffre faux d'un ordre de
    grandeur.
    """
    settings = get_settings()
    monde = _univers(univers)

    async def run() -> tuple[list[tuple], tuple]:
        async with (
            connect(settings.database_url, schema=settings.db_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                select kind, count(*) as lignes, count(distinct source_id) as objets,
                       sum(pg_column_size(payload))::bigint as octets,
                       max(fetched_at)::timestamp(0) as dernier
                from raw_source where source = 'tmdb'
                group by kind order by kind
                """
            )
            rows = await cur.fetchall()

            # Ce que la table occupe réellement sur le disque, index et
            # compression TOAST compris. C'est la mesure que `df -h` verra —
            # mais elle porte sur la table ENTIÈRE, tous univers confondus.
            # C'est le rapport entre elle et le poids des payloads qui sert :
            # il donne le surcoût de structure, et celui-là s'applique à
            # n'importe quel univers.
            await cur.execute(
                """
                select (select count(distinct source_id) from raw_source
                        where source = 'tmdb' and kind = %(kind)s),
                       pg_total_relation_size('raw_source'),
                       (select count(*) from tmdb_catalog where univers = %(univers)s)
                """,
                {"kind": monde.kind, "univers": monde.cle},
            )
            return rows, await cur.fetchone()

    rows, (faites, octets, catalogue) = _run_db(run)
    if not rows:
        typer.echo("raw_source est vide.")
        return

    espace = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731

    typer.echo(f"{'type':<12}{'lignes':>9}{'objets':>9}{'poids':>12}  dernier")
    for kind, lignes, objets, octets, dernier in rows:
        typer.echo(f"{kind:<12}{lignes:>9}{objets:>9}{_octets(octets or 0):>12}  {dernier}")

    # La projection, et le piège qu'elle a tendu une fois.
    #
    # Diviser `pg_total_relation_size` par le nombre d'œuvres de l'univers
    # demandé donne un résultat absurde dès que deux univers cohabitent : le
    # 2026-08-12, 9,3 Go de séries divisés par 500 films annonçaient 28,6 Mo
    # par film et **33,6 To** pour le catalogue — faux d'un facteur 430, et
    # assez effrayant pour dissuader de lancer la passe.
    #
    # On mesure donc le poids des payloads de CET univers — les deux `kind`
    # d'une série, le seul d'un film — et on lui applique le surcoût de
    # structure observé sur la table entière (index, TOAST). Les deux nombres
    # viennent de requêtes qu'on faisait déjà.
    mien = {kind for kind in kinds_de(monde)}
    octets_univers = sum(ligne[3] or 0 for ligne in rows if ligne[0] in mien)
    octets_payloads = sum(ligne[3] or 0 for ligne in rows)
    surcout = (octets / octets_payloads) if octets_payloads else 1.0

    # Sous ~100 œuvres l'extrapolation ne vaut rien : la taille varie d'un
    # facteur dix entre un pilote sans suite et une série de quinze saisons.
    if faites >= 100 and catalogue and octets_univers:
        par_oeuvre = octets_univers / faites * surcout
        projection = par_oeuvre * catalogue
        typer.echo("")
        typer.echo(f"univers       : {monde.cle}")
        typer.echo(f"mesuré sur    : {faites} {monde.libelle}(s) collecté(s)")
        typer.echo(
            f"par {monde.libelle:<10}: {_octets(par_oeuvre)}  (dont ×{surcout:.2f} de structure)"
        )
        typer.echo(
            f"projection    : {_octets(projection)} pour {espace(catalogue)} {monde.libelle}(s)"
        )
        typer.echo("                (index compris ; vérifier `df -h` avant la passe complète)")
        typer.echo(
            "                ⚠️ un échantillon pris par popularité est le plus lourd du catalogue :"
        )
        typer.echo("                   la projection est un plafond, pas une moyenne.")
    elif catalogue:
        typer.echo("")
        typer.echo(
            f"Projection de volume à partir de 100 {monde.libelle}s ({faites} pour l'instant)."
        )


def _octets(taille: float) -> str:
    for unite in ("o", "Ko", "Mo", "Go", "To"):
        if taille < 1024 or unite == "To":
            return f"{taille:.1f} {unite}"
        taille /= 1024
    return f"{taille:.1f} To"


@app.command("import-v1")
def import_v1_cmd(
    dossier: Annotated[
        Path,
        typer.Option("--dossier", help="Répertoire de l'export V1 (contenant manifest.json)."),
    ] = Path("/imports"),
) -> None:
    """Importe l'export V1 — membres, tops, découvertes, avis.

    Rejouable : chaque table s'écrit sur sa clé V1, relancer ne duplique rien.
    Sur le serveur, le répertoire arrive par `./imports` monté dans le
    conteneur :

        docker compose run --rm sourcing import-v1

    À la fin, si des fiches TMDB citées n'ont jamais été collectées, leur
    liste sort dans `a-collecter-<univers>.txt` — les pivots existent déjà,
    l'import n'attend pas ces fiches.
    """
    from fiv_sourcing.import_v1 import importer

    settings = get_settings()
    if not (dossier / "manifest.json").is_file():
        typer.echo(f"ERREUR : pas de manifest.json dans {dossier}")
        typer.echo("        → l'export V1 se produit avec tools/export_v1.py, et le")
        typer.echo("          répertoire se monte dans le conteneur (volume ./imports).")
        raise typer.Exit(2)

    typer.echo(f"cible  : {redact_dsn(settings.database_url)} (schéma {settings.db_schema})")
    typer.echo(f"source : {dossier}")

    async def run():
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            await _exiger_le_schema_a_jour(conn, settings)
            return await importer(conn, dossier)

    debut = time.monotonic()
    r = _run_db(run)
    typer.echo(
        f"œuvres      : {r.oeuvres_tmdb} par id TMDB, {r.oeuvres_titre} par titre, "
        f"{r.oeuvres_creees} créées depuis la V1"
    )
    for univers, ids in r.a_collecter.items():
        typer.echo(
            f"              {len(ids)} fiches {univers} jamais collectées "
            f"→ a-collecter-{univers}.txt (les pivots existent)"
        )
    typer.echo(f"membres     : {r.membres}, dont {r.identifiants} avec un compte")
    typer.echo(
        f"fives       : {r.fives}  ({r.positions} positions, "
        f"{r.positions_ecartees} écartées — vides, doublons, orphelines)"
    )
    typer.echo(f"découvertes : {r.decouvertes}  ({r.decouvertes_ecartees} écartées)")
    typer.echo(
        f"avis        : {r.avis}  ({r.avis_ecartes} écartés, {r.reponses_recousues} fils recousus)"
    )
    typer.echo(f"terminé en {_duree(time.monotonic() - debut)}")


async def _exiger_le_schema_a_jour(conn: psycopg.AsyncConnection, settings: Settings) -> None:
    """Refuse de démarrer une passe sur un schéma en retard.

    Le cas s'est produit trois fois de suite sur le serveur, sous trois formes :
    migration jamais copiée dans l'image, commande absente, colonne manquante.
    La dernière se manifestait par `column c.first_air_date does not exist` au
    milieu d'une trace psycopg — un message qui dit ce qui a cassé mais pas quoi
    faire. Une passe dure des heures : elle doit échouer sur la première seconde
    et dire la commande à lancer.
    """
    attente = await pending_migrations(conn, settings.migrations_dir)
    if not attente:
        return
    typer.echo(f"ERREUR : {len(attente)} migration(s) en attente : {', '.join(attente)}")
    typer.echo("        → `db migrate` d'abord.")
    typer.echo("          En conteneur, reconstruire l'image avant : les migrations")
    typer.echo("          y sont copiées, un `git pull` seul ne les y met pas.")
    raise typer.Exit(1)


async def _db_status(dsn: str, schema: str, migrations_dir: Path) -> tuple[str, int, int]:
    """Version du serveur, migrations en attente, tables présentes dans le schéma."""
    async with connect(dsn, schema=schema) as conn:
        version = await ping(conn)
        async with conn.cursor() as cur:
            await cur.execute("select to_regclass('public.schema_migrations') is not null")
            row = await cur.fetchone()
            applied: set[str] = set()
            if row and row[0]:
                await cur.execute("select version from public.schema_migrations")
                applied = {r[0] for r in await cur.fetchall()}

            await cur.execute(
                "select count(*) from information_schema.tables where table_schema = %s",
                (schema,),
            )
            tables = (await cur.fetchone())[0]

    pending = len([p for p in migrations_dir.glob("*.sql") if p.stem not in applied])
    return version, pending, tables


async def _tmdb_check(settings: Settings) -> int:
    """Code HTTP renvoyé par TMDB sur un appel authentifié. 0 si injoignable."""
    from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher

    fetcher = build_fetcher(settings)
    async with fetcher:
        return (await TmdbClient(fetcher, settings).configuration()).status


def _http_label(status: int) -> str:
    if status == 0:
        return "aucune réponse"
    return f"HTTP {status}" + (" (valide)" if status == 200 else " (refusé)")


def _univers(cle: str) -> Univers:
    """Résout `--univers` pour une commande TMDB, et s'arrête sur une valeur
    inconnue — ou sans collecte TMDB (livres).

    Liste fermée : une faute de frappe doit échouer ici plutôt que de créer un
    troisième univers silencieux dans `tmdb_catalog` — qui ne se verrait qu'au
    moment où la grille de l'admin n'afficherait rien.
    """
    try:
        return resoudre_tmdb(cle)
    except ValueError as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(2) from exc


def _univers_crawl(cle: str) -> Univers:
    """Résout `--univers` pour le crawler : il faut des classes Wikidata à
    balayer — les séries et les livres en ont, les films n'en ont pas (le
    flux 1 les couvre, et leur crawler n'est pas écrit)."""
    try:
        monde = resoudre(cle)
    except ValueError as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(2) from exc
    if not monde.wikidata_classes:
        typer.echo(f"ERREUR : pas de crawler pour l'univers {monde.cle}")
        raise typer.Exit(2)
    return monde


def _run_db[T](factory: Callable[[], Coroutine[object, object, T]]) -> T:
    """Exécute une coroutine qui parle à la base, en traduisant les échecs
    d'infrastructure en messages actionnables.

    Une trace Python de trente lignes sur un `ConnectionTimeout` ne dit pas ce
    qu'il faut aller regarder ; ces trois lignes-là, si.
    """
    try:
        return asyncio.run(factory())
    except MigrationsNotFound as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc
    except psycopg.OperationalError as exc:
        dsn = redact_dsn(get_settings().database_url)
        message = str(exc).strip() or type(exc).__name__
        typer.echo(f"ERREUR : connexion impossible à {dsn}")
        typer.echo(f"         {message}")
        if isinstance(exc, psycopg.errors.ConnectionTimeout):
            # Un refus dirait « personne n'écoute ». Un délai dépassé dit que
            # les paquets sont jetés en silence — pare-feu, pas Postgres.
            typer.echo("         → délai dépassé, pas un refus : les paquets sont filtrés.")
            typer.echo("           Vérifier la chaîne INPUT du pare-feu de l'hôte, que")
            typer.echo("           Docker ne configure pas (il ne touche qu'à FORWARD/NAT).")
        else:
            typer.echo("         → vérifier `ss -lntp | grep 5432` et pg_hba.conf sur l'hôte.")
        raise typer.Exit(1) from exc


def _line(label: str, ok: bool, detail: str) -> bool:
    typer.echo(f"  {'✓' if ok else '✗'}  {label:<18} {detail}")
    return ok


if __name__ == "__main__":
    app()
