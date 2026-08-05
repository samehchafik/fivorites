"""Point d'entrée en ligne de commande."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer

from fiv_sourcing.config import VENDOR_DIR, get_settings
from fiv_sourcing.db import connect, migrate, ping

app = typer.Typer(help="Acquisition de données Fivorites V2 — séries", no_args_is_help=True)
db_app = typer.Typer(help="Base de données", no_args_is_help=True)
tmdb_app = typer.Typer(help="Source TMDB", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(tmdb_app, name="tmdb")


@app.callback()
def _root(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )


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

    creds = "token v4" if settings.tmdb_bearer else ("clé v3" if settings.tmdb_api_key else "aucun")
    ok &= _line("identifiants TMDB", settings.has_tmdb_credentials, creds)

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

    async def run() -> list[str]:
        async with connect(settings.database_url, schema=settings.db_schema) as conn:
            return await migrate(conn, settings.migrations_dir)

    applied = asyncio.run(run())
    detail = f" : {', '.join(applied)}" if applied else ""
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

    raise typer.Exit(1 if asyncio.run(run()) else 0)


@tmdb_app.command("stats")
def tmdb_stats() -> None:
    """Ce qu'il y a en base, par type d'objet."""
    settings = get_settings()

    async def run() -> list[tuple]:
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
            return await cur.fetchall()

    rows = asyncio.run(run())
    if not rows:
        typer.echo("raw_source est vide.")
        return
    typer.echo(f"{'type':<12}{'lignes':>9}{'objets':>9}{'poids':>12}  dernier")
    for kind, lignes, objets, poids, dernier in rows:
        typer.echo(f"{kind:<12}{lignes:>9}{objets:>9}{poids or '-':>12}  {dernier}")


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


def _line(label: str, ok: bool, detail: str) -> bool:
    typer.echo(f"  {'✓' if ok else '✗'}  {label:<18} {detail}")
    return ok


if __name__ == "__main__":
    app()
