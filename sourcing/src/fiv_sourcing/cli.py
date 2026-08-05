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
from fiv_sourcing.db import MigrationsNotFound, connect, migrate, ping
from fiv_sourcing.http import FetcherStats
from fiv_sourcing.redact import SecretFilter, fingerprint, redact_dsn

app = typer.Typer(help="Acquisition de données Fivorites V2 — séries", no_args_is_help=True)
db_app = typer.Typer(help="Base de données", no_args_is_help=True)
tmdb_app = typer.Typer(help="Source TMDB", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(tmdb_app, name="tmdb")


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
    ids: Annotated[list[int], typer.Option("--id", help="Id TMDB de la série (répétable)")],
) -> None:
    """Collecte une ou plusieurs séries dans `raw_source`."""
    from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher
    from fiv_sourcing.sources.tmdb.collect import collect_series

    settings = get_settings()
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
                    report = await collect_series(conn, client, tv_id)
                    marker = "ok " if report.ok else "ÉCHEC"
                    typer.echo(
                        f"{marker} {tv_id:>8}  {report.requests:>3} requêtes  "
                        f"{report.seasons_seen:>2} saisons  "
                        f"{report.rows_written:>3} ligne(s) écrite(s)"
                    )
                    for error in report.errors[:3]:
                        typer.echo(f"         {error}")
                    failures += int(not report.ok)
        return failures

    raise typer.Exit(1 if _run_db(run) else 0)


@tmdb_app.command("export")
def tmdb_export(
    day: Annotated[
        str | None,
        typer.Option(
            "--date", help="Export d'un jour donné (AAAA-MM-JJ). Défaut : le plus récent."
        ),
    ] = None,
) -> None:
    """Récupère la liste de toutes les séries depuis l'export quotidien TMDB.

    Fichier public, aucune clé d'API requise, aucun quota consommé.
    """
    from fiv_sourcing.sources.tmdb.client import build_public_fetcher
    from fiv_sourcing.sources.tmdb.export import ExportUnavailable, refresh_catalog

    settings = get_settings()
    wanted = date.fromisoformat(day) if day else None

    async def run() -> ExportReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            fetcher = build_public_fetcher(settings)
            async with fetcher:
                return await refresh_catalog(conn, fetcher, wanted)

    try:
        report = _run_db(run)
    except ExportUnavailable as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc

    typer.echo(f"export       : {report.url}")
    typer.echo(f"date         : {report.exported_on}")
    typer.echo(f"séries lues  : {report.series_read:>9,}".replace(",", " "))
    typer.echo(f"nouvelles    : {report.inserted:>9,}".replace(",", " "))
    typer.echo(f"mises à jour : {report.updated:>9,}".replace(",", " "))


@tmdb_app.command("changes")
def tmdb_changes(
    days: Annotated[int, typer.Option("--days", help="Fenêtre en jours. TMDB plafonne à 14.")] = 1,
) -> None:
    """Marque les séries que TMDB signale comme modifiées.

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
                return await refresh_changes(conn, TmdbClient(fetcher, settings), days=days)

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
    typer.echo("`tmdb backfill` recollectera les séries marquées.")


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
) -> None:
    """Collecte tout le catalogue. Reprend là où la passe précédente s'est arrêtée.

    Aucun filtre : ce qui mérite d'être montré se décide en aval, sur des
    données complètes.
    """
    from fiv_sourcing.sources.tmdb.backfill import BackfillReport, backfill, pending_ids
    from fiv_sourcing.sources.tmdb.client import TmdbClient, build_fetcher

    settings = get_settings()
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
            f"{rate:5.2f} série/s  reste {_duree(eta)}"
        )

    async def run() -> BackfillReport:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            ids = await pending_ids(conn, refresh_after=refresh_after, limit=limit, order=order)
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
                )
                stats.append(fetcher.stats)
                return report

    typer.echo(f"langues : {', '.join(settings.season_languages)}")
    typer.echo(f"débit   : {settings.tmdb_rate_limit} requête/s (TMDB_RATE_LIMIT)")
    stats: list[FetcherStats] = []
    report = _run_db(run)

    if dry_run:
        typer.echo(f"à collecter : {report.selected} série(s)")
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
        typer.echo(f"Interrompu — {report.remaining} série(s) restantes.")
        typer.echo("Relancer la même commande reprend où on s'est arrêté.")
        raise typer.Exit(130)


def _bilan_debit(stats: FetcherStats, rate_limit: float) -> None:
    """Ce que la passe apprend sur le plafond réellement toléré par TMDB.

    Leur limite dure a été supprimée en 2019 et ce qui subsiste n'est pas
    documenté : plutôt que de régler le débit sur une valeur trouvée dans un
    forum, on regarde combien de 429 une passe réelle a déclenchés.
    """
    typer.echo("")
    typer.echo(f"requêtes HTTP : {stats.requests}  (dont {stats.retries} reprise(s))")
    typer.echo(f"429 reçus     : {stats.rate_limited}")
    if stats.transport_errors:
        typer.echo(f"erreurs réseau: {stats.transport_errors}")

    if not stats.rate_limited:
        typer.echo(
            f"              → aucun bridage à {rate_limit} req/s. "
            "Monter TMDB_RATE_LIMIT accélérerait la passe."
        )
    elif stats.rate_limited_ratio > 0.01:
        typer.echo(
            f"              → {stats.rate_limited_ratio:.1%} des requêtes bridées. "
            "Baisser TMDB_RATE_LIMIT : les reprises coûtent plus qu'elles ne rapportent."
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
def tmdb_catalog() -> None:
    """Volumétrie du catalogue et répartition par popularité."""
    settings = get_settings()

    async def run() -> tuple[tuple, list[tuple]]:
        async with (
            connect(settings.database_url, schema=settings.db_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                select count(*), count(*) filter (where adult),
                       max(exported_on), count(*) filter (where exported_on < (
                           select max(exported_on) from tmdb_catalog))
                from tmdb_catalog
                """
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
                    from tmdb_catalog
                ) t
                group by decile order by decile
                """
            )
            return resume, await cur.fetchall()

    (total, adultes, dernier_export, disparues), deciles = _run_db(run)

    if not total:
        typer.echo("Catalogue vide. Lancer `tmdb export` d'abord.")
        raise typer.Exit(1)

    espace = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731
    typer.echo(f"séries          : {espace(total)}")
    typer.echo(f"dont adulte     : {espace(adultes)}")
    typer.echo(f"dernier export  : {dernier_export}")
    typer.echo(f"absentes depuis : {espace(disparues)}  (supprimées de TMDB)")
    typer.echo("")
    typer.echo(f"{'décile':<8}{'séries':>10}{'popularité max':>16}{'min':>12}")
    for decile, nombre, maxi, mini in deciles:
        typer.echo(f"{decile:<8}{espace(nombre):>10}{maxi:>16.2f}{mini:>12.2f}")


@tmdb_app.command("stats")
def tmdb_stats() -> None:
    """Ce qu'il y a en base, par type d'objet."""
    settings = get_settings()

    async def run() -> tuple[list[tuple], tuple]:
        async with (
            connect(settings.database_url, schema=settings.db_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                select kind, count(*) as lignes, count(distinct source_id) as objets,
                       pg_size_pretty(sum(pg_column_size(payload))::bigint) as poids,
                       max(fetched_at)::timestamp(0) as dernier
                from raw_source where source = 'tmdb'
                group by kind order by kind
                """
            )
            rows = await cur.fetchall()

            # Projection sur le catalogue entier. `pg_total_relation_size` plutôt
            # que la taille des payloads : il inclut les index et la compression
            # TOAST, donc il mesure ce que le disque va réellement encaisser.
            await cur.execute(
                """
                select (select count(distinct source_id) from raw_source
                        where source = 'tmdb' and kind = 'tv'),
                       pg_total_relation_size('raw_source'),
                       (select count(*) from tmdb_catalog)
                """
            )
            return rows, await cur.fetchone()

    rows, (series_faites, octets, catalogue) = _run_db(run)
    if not rows:
        typer.echo("raw_source est vide.")
        return

    typer.echo(f"{'type':<12}{'lignes':>9}{'objets':>9}{'poids':>12}  dernier")
    for kind, lignes, objets, poids, dernier in rows:
        typer.echo(f"{kind:<12}{lignes:>9}{objets:>9}{poids or '-':>12}  {dernier}")

    # Sous ~100 séries l'extrapolation ne vaut rien : la taille varie d'un
    # facteur dix entre un pilote sans suite et une série de quinze saisons.
    if series_faites >= 100 and catalogue:
        par_serie = octets / series_faites
        projection = par_serie * catalogue
        typer.echo("")
        typer.echo(f"mesuré sur    : {series_faites} série(s)")
        typer.echo(f"par série     : {_octets(par_serie)}")
        typer.echo(f"projection    : {_octets(projection)} pour {catalogue} séries")
        typer.echo("                (index compris ; vérifier `df -h` avant la passe complète)")
    elif catalogue:
        typer.echo("")
        typer.echo(f"Projection de volume à partir de 100 séries ({series_faites} pour l'instant).")


def _octets(taille: float) -> str:
    for unite in ("o", "Ko", "Mo", "Go", "To"):
        if taille < 1024 or unite == "To":
            return f"{taille:.1f} {unite}"
        taille /= 1024
    return f"{taille:.1f} To"


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
