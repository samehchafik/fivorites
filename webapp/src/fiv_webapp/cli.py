"""Point d'entrée en ligne de commande du site public.

Trois gestes : migrer le schéma `visiteur`, lancer le service, vérifier
l'environnement. Tout le reste — index ES, projection du graphe — appartient
à `fiv-admin` : ce service LIT ce que l'admin entretient.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Coroutine
from typing import Annotated, Any

import typer

from fiv_webapp.config import get_settings
from fiv_webapp.db import MigrationsNotFound, connect, migrate

app = typer.Typer(help="Site public Fivorites V2 — recherche et suggestions", no_args_is_help=True)
db_app = typer.Typer(help="Base de données", no_args_is_help=True)
app.add_typer(db_app, name="db")


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


async def _migrer() -> list[str]:
    settings = get_settings()
    async with connect(settings.database_url) as conn:
        return await migrate(conn, settings.migrations_dir)


@db_app.command("migrate")
def db_migrate() -> None:
    """Applique les migrations du schéma `visiteur`."""
    try:
        appliquees = _run(_migrer())
    except MigrationsNotFound as exc:
        typer.echo(f"ERREUR : {exc}")
        raise typer.Exit(1) from exc
    if appliquees:
        for version in appliquees:
            typer.echo(f"appliquée : {version}")
    else:
        typer.echo("rien à appliquer")


@app.command("courriel-test")
def courriel_test(
    adresse: Annotated[str, typer.Argument(help="L'adresse qui doit recevoir le test.")],
) -> None:
    """Envoie un courriel de test par le MÊME chemin que le code d'inscription.

    C'est le contrôle du SMTP configuré : si ce test arrive, les codes de
    vérification arriveront. Sans SMTP_HOST, la commande le dit et montre ce
    que le service ferait — écrire le code au journal.
    """
    import logging

    from fiv_webapp.comptes import generer_code
    from fiv_webapp.courriel import Courriel

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    courriel = Courriel(
        settings.smtp_host,
        port=settings.smtp_port,
        utilisateur=settings.smtp_user,
        mot_de_passe=settings.smtp_password,
        expediteur=settings.smtp_from,
    )
    if not courriel.configure:
        typer.echo("SMTP_HOST est vide : aucun courriel ne peut partir.")
        typer.echo("Le service écrirait le code au journal — démonstration :")
    code = generer_code()
    _run(courriel.envoyer_code(adresse, "Test", code, "fr"))
    if courriel.configure:
        typer.echo(f"envoyé à {adresse} (code de démonstration : {code})")
        typer.echo("si rien n'arrive : vérifier le dossier spam, puis les identifiants SMTP.")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Rechargement à chaud (dev).")] = False,
) -> None:
    """Lance l'API (et le site, s'il est construit)."""
    import uvicorn

    settings = get_settings()
    if not settings.secret_key:
        typer.echo("⚠ SECRET_KEY absente : les sessions ne survivront pas au redémarrage.")
        typer.echo(f"  suggestion : SECRET_KEY={secrets.token_hex(32)}")

    typer.echo(f"site : {settings.web_dist if settings.has_front else 'non construit'}")

    uvicorn.run(
        "fiv_webapp.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


async def _doctor() -> int:
    settings = get_settings()
    code = 0
    try:
        async with connect(settings.database_url) as conn, conn.cursor() as cur:
            await cur.execute(
                "select exists (select 1 from information_schema.tables"
                " where table_schema = 'visiteur' and table_name = 'signal')"
            )
            ligne = await cur.fetchone()
        typer.echo("base : OK")
        if ligne and ligne[0]:
            typer.echo("schéma visiteur : OK")
        else:
            typer.echo("schéma visiteur : ABSENT — lancer `make migrate`")
            code = 1
    except Exception as exc:  # noqa: BLE001 — le doctor rapporte, il ne plante pas
        typer.echo(f"base : INJOIGNABLE — {exc}")
        code = 1
    typer.echo(f"site construit : {'oui' if settings.has_front else 'non (make -C site build)'}")
    return code


@app.command()
def doctor() -> None:
    """Vérifie l'environnement : base, schéma, build du site."""
    raise typer.Exit(_run(_doctor()))


if __name__ == "__main__":
    app()
