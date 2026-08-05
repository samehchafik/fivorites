"""Point d'entrée en ligne de commande.

Les comptes se gèrent ici et nulle part ailleurs : le front n'a ni inscription
ni création d'utilisateur.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Coroutine
from typing import Annotated, Any

import psycopg
import typer

from fiv_admin.config import VENDOR_DIR, get_settings
from fiv_admin.db import MigrationsNotFound, connect, migrate
from fiv_admin.redact import SecretFilter, redact_dsn
from fiv_admin.security import hash_password

app = typer.Typer(help="Administration Fivorites V2 — suivi de l'acquisition", no_args_is_help=True)
db_app = typer.Typer(help="Base de données", no_args_is_help=True)
user_app = typer.Typer(help="Comptes d'administration", no_args_is_help=True)
catalog_app = typer.Typer(help="Projection d'affichage du catalogue", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(user_app, name="user")
app.add_typer(catalog_app, name="catalog")


@catalog_app.command("refresh")
def catalog_refresh() -> None:
    """Recalcule les vignettes depuis le brut.

    À lancer après une passe de collecte : la grille de cartes lit cette
    projection, pas le brut, et reste donc en retard jusque-là. Le détail d'une
    série, lui, relit toujours le brut.
    """
    from fiv_admin.catalog import refresh_cards

    settings = get_settings()

    async def run() -> int:
        async with connect(settings.database_url, settings.sourcing_schema) as conn:
            return await refresh_cards(conn)

    typer.echo(f"{_run(run()):,} vignette(s) dans la projection".replace(",", " "))


@app.callback()
def _root(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    # Posé sur le gestionnaire, pas sur un logger particulier : une fuite vient
    # presque toujours d'une bibliothèque tierce, et on ne veut pas dépendre de
    # la liste de celles qui journalisent des URL.
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter())


@app.command()
def serve(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Rechargement à chaud (dev).")] = False,
) -> None:
    """Lance l'API (et le front, s'il est construit)."""
    import uvicorn

    settings = get_settings()
    if not settings.admin_secret_key:
        typer.echo("⚠ ADMIN_SECRET_KEY absente : les sessions ne survivront pas au redémarrage.")
        typer.echo(f"  suggestion : ADMIN_SECRET_KEY={secrets.token_hex(32)}")

    typer.echo(f"base  : {redact_dsn(settings.database_url)}")
    typer.echo(f"front : {settings.web_dist if settings.has_front else 'non construit'}")

    uvicorn.run(
        "fiv_admin.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@app.command()
def doctor() -> None:
    """Vérifie l'environnement : interpréteur, base, migrations, comptes, front."""
    import sys
    from pathlib import Path

    settings = get_settings()
    ok = True

    if VENDOR_DIR.exists():
        base = Path(sys.base_prefix).resolve()
        vendored = (
            VENDOR_DIR in Path(sys.executable).resolve().parents or VENDOR_DIR in base.parents
        )
        ok &= _line("interpréteur", vendored, f"{sys.version.split()[0]} — {base}")
        if not vendored:
            typer.echo("        → Python hors vendor/. Relancer `make bootstrap`.")
    else:
        _line("interpréteur", True, f"{sys.version.split()[0]} — image, pas de vendor/")

    ok &= _line(
        "secret de session",
        bool(settings.admin_secret_key),
        "configuré" if settings.admin_secret_key else "absent — sessions éphémères",
    )

    try:
        state = _run(_status())
    except Exception as exc:  # noqa: BLE001 — on veut le message brut
        ok &= _line("base", False, f"{type(exc).__name__}: {exc}")
        typer.echo(
            "        → la base est celle de sourcing : `make -C ../sourcing db-create migrate`."
        )
    else:
        ok &= _line("base", True, redact_dsn(settings.database_url))
        ok &= _line(
            "schéma sourcing",
            state["sourcing"],
            "présent" if state["sourcing"] else "absent — migrer sourcing d'abord",
        )
        ok &= _line(
            "schéma admin",
            state["admin"],
            "présent" if state["admin"] else "absent — `fiv-admin db migrate`",
        )
        if state["admin"]:
            ok &= _line(
                "comptes",
                state["users"] > 0,
                f"{state['users']}" if state["users"] else "aucun — `fiv-admin user add`",
            )
        ok &= _line(
            "catalogue", state["catalog"] > 0, f"{state['catalog']:,} séries".replace(",", " ")
        )

    _line(
        "front construit",
        settings.has_front,
        str(settings.web_dist)
        if settings.has_front
        else f"pas d'index.html dans {settings.web_dist} — `make web-build`",
    )

    raise typer.Exit(0 if ok else 1)


@db_app.command("migrate")
def db_migrate() -> None:
    """Applique les migrations du schéma `admin`."""
    settings = get_settings()
    typer.echo(f"cible      : {redact_dsn(settings.database_url)}")
    typer.echo(f"migrations : {settings.migrations_dir}")

    async def run() -> list[str]:
        async with connect(settings.database_url) as conn:
            return await migrate(conn, settings.migrations_dir)

    try:
        applied = _run(run())
    except MigrationsNotFound as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc
    except psycopg.errors.RaiseException as exc:
        typer.echo(f"ERREUR : {exc.diag.message_primary or exc}")
        raise typer.Exit(1) from exc

    detail = f" : {', '.join(applied)}" if applied else " (base déjà à jour)"
    typer.echo(f"{len(applied)} migration(s) appliquée(s){detail}")


@user_app.command("add")
def user_add(
    username: Annotated[str, typer.Argument(help="Identifiant de connexion.")],
    display_name: Annotated[str | None, typer.Option("--name", help="Nom affiché.")] = None,
) -> None:
    """Crée un compte. Le mot de passe est demandé, jamais passé en argument —
    une ligne de commande finit dans l'historique du shell."""
    # Vérifié avant l'invite, pas après : se faire saisir un mot de passe deux
    # fois pour apprendre ensuite que la table n'existe pas est le genre de
    # détail qui use.
    _require_admin_schema()

    password = typer.prompt("Mot de passe", hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        typer.echo("Mot de passe trop court : 12 caractères au minimum.")
        raise typer.Exit(2)

    settings = get_settings()

    async def run() -> bool:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                insert into admin_user (username, password_hash, display_name)
                values (%s, %s, %s)
                on conflict (username) do nothing
                returning username
                """,
                (username, hash_password(password), display_name),
            )
            return await cur.fetchone() is not None

    if not _run(run()):
        typer.echo(f"Le compte {username} existe déjà — `fiv-admin user passwd {username}`.")
        raise typer.Exit(1)
    typer.echo(f"Compte {username} créé.")


@user_app.command("passwd")
def user_passwd(username: str) -> None:
    """Change le mot de passe d'un compte."""
    password = typer.prompt("Nouveau mot de passe", hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        typer.echo("Mot de passe trop court : 12 caractères au minimum.")
        raise typer.Exit(2)

    settings = get_settings()

    async def run() -> bool:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                update admin_user set password_hash = %s
                where username = %s
                returning username
                """,
                (hash_password(password), username),
            )
            return await cur.fetchone() is not None

    if not _run(run()):
        typer.echo(f"Compte inconnu : {username}")
        raise typer.Exit(1)
    typer.echo(f"Mot de passe de {username} changé.")


@user_app.command("disable")
def user_disable(
    username: str,
    enable: Annotated[
        bool, typer.Option("--enable", help="Réactiver au lieu de désactiver.")
    ] = False,
) -> None:
    """Désactive (ou réactive) un compte. Effet immédiat : les sessions en
    cours sont refusées à la requête suivante."""
    settings = get_settings()

    async def run() -> bool:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "update admin_user set disabled = %s where username = %s returning username",
                (not enable, username),
            )
            return await cur.fetchone() is not None

    if not _run(run()):
        typer.echo(f"Compte inconnu : {username}")
        raise typer.Exit(1)
    typer.echo(f"Compte {username} {'réactivé' if enable else 'désactivé'}.")


@user_app.command("list")
def user_list() -> None:
    """Liste les comptes."""
    settings = get_settings()

    async def run() -> list[tuple[Any, ...]]:
        async with (
            connect(settings.database_url, settings.admin_schema) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "select username, display_name, disabled, created_at, last_login_at"
                " from admin_user order by username"
            )
            return list(await cur.fetchall())

    rows = _run(run())
    if not rows:
        typer.echo("Aucun compte. `fiv-admin user add <identifiant>`")
        return
    for username, name, disabled, created, last in rows:
        state = "désactivé" if disabled else "actif"
        seen = last.strftime("%Y-%m-%d %H:%M") if last else "jamais connecté"
        typer.echo(f"{username:<20} {state:<10} {name or '':<24} créé {created:%Y-%m-%d}  {seen}")


async def _status() -> dict[str, Any]:
    settings = get_settings()
    async with connect(settings.database_url) as conn, conn.cursor() as cur:
        await cur.execute(
            "select schema_name from information_schema.schemata"
            " where schema_name = any(%s::text[])",
            ([settings.sourcing_schema, settings.admin_schema],),
        )
        present = {row[0] for row in await cur.fetchall()}

        users = 0
        if settings.admin_schema in present:
            await cur.execute(
                f'select count(*) from "{settings.admin_schema}".admin_user'  # noqa: S608
            )
            users = (await cur.fetchone() or (0,))[0]

        catalog = 0
        if settings.sourcing_schema in present:
            await cur.execute(
                f'select count(*) from "{settings.sourcing_schema}".tmdb_catalog'  # noqa: S608
            )
            catalog = (await cur.fetchone() or (0,))[0]

    return {
        "sourcing": settings.sourcing_schema in present,
        "admin": settings.admin_schema in present,
        "users": users,
        "catalog": catalog,
    }


def _require_admin_schema() -> None:
    """Échoue avec une consigne si `admin.admin_user` n'existe pas.

    C'est l'état d'une base migrée pour `sourcing` mais pas encore pour
    l'administration — le cas normal au premier déploiement. Sans ce contrôle,
    la première commande de compte se termine par une trace `UndefinedTable`,
    qui dit *quelle table* manque mais pas *quoi faire*.
    """
    settings = get_settings()

    async def run() -> str | None:
        async with connect(settings.database_url) as conn, conn.cursor() as cur:
            await cur.execute("select to_regclass(%s)", (f"{settings.admin_schema}.admin_user",))
            row = await cur.fetchone()
        return row[0] if row else None

    if _run(run()) is None:
        typer.echo(f"Le schéma « {settings.admin_schema} » n'existe pas encore.")
        typer.echo("→ appliquer les migrations d'abord :")
        typer.echo("     fiv-admin db migrate")
        typer.echo("   en conteneur :")
        typer.echo("     docker compose run --rm admin db migrate")
        typer.echo("")
        typer.echo("   Si cette commande échoue sur « schéma sourcing absent », c'est que")
        typer.echo("   la collecte n'a pas encore migré cette base :")
        typer.echo("     docker compose run --rm sourcing db migrate")
        raise typer.Exit(1)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coro)
    except psycopg.OperationalError as exc:
        typer.echo(f"ERREUR de connexion : {exc}")
        typer.echo("→ vérifier DATABASE_URL dans admin/.env")
        raise typer.Exit(1) from exc
    except psycopg.errors.UndefinedTable as exc:
        # Le filet pour les autres commandes de compte, qui n'ont pas d'invite
        # à protéger et vont donc droit à la requête.
        typer.echo(f"ERREUR : {exc}")
        typer.echo("→ le schéma de l'administration n'est pas créé :")
        typer.echo("     fiv-admin db migrate")
        raise typer.Exit(1) from exc


def _line(label: str, ok: bool, detail: str = "") -> bool:
    typer.echo(f"  {'✓' if ok else '✗'}  {label:<20} {detail}")
    return ok
