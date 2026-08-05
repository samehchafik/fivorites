"""Connexion Postgres, pool et migrations.

Le `search_path` est posé une fois par connexion — `sourcing`, puis `admin`,
puis `public`. Le code applicatif écrit donc `raw_source` et `admin_user` sans
préfixe, et changer de schéma reste un réglage. Les migrations, elles,
qualifient tout explicitement.

Ce module reprend la mécanique de `fiv_sourcing.db`. Le doublon est assumé :
les deux modules se déploient séparément (le pipeline est un traitement par
lots, l'administration un service permanent), et les coupler pour une
quarantaine de lignes ferait entrer httpx et le client TMDB dans l'image du
front.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

_MIGRATIONS_TABLE = """
create table if not exists public.schema_migrations (
    version    text        primary key,
    applied_at timestamptz not null default now()
)
"""


def search_path(*schemas: str) -> sql.Composed:
    return sql.SQL("set search_path to {}, public").format(
        sql.SQL(", ").join(sql.Identifier(s) for s in schemas)
    )


@asynccontextmanager
async def connect(dsn: str, *schemas: str) -> AsyncIterator[psycopg.AsyncConnection]:
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    try:
        if schemas:
            await conn.execute(search_path(*schemas))
        yield conn
    finally:
        await conn.close()


def build_pool(dsn: str, *schemas: str, max_size: int = 8) -> AsyncConnectionPool:
    """Pool du service web. Ouvert par le cycle de vie de l'application.

    `open=False` : le pool ne se connecte qu'au démarrage de l'application, pas
    à l'import — sinon les tests et `--help` tenteraient une connexion.
    """

    async def configure(conn: psycopg.AsyncConnection) -> None:
        await conn.execute(search_path(*schemas))

    return AsyncConnectionPool(
        dsn,
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True},
        configure=configure if schemas else None,
    )


class MigrationsNotFound(RuntimeError):
    """Le répertoire de migrations est absent ou vide."""


async def migrate(conn: psycopg.AsyncConnection, migrations_dir: Path) -> list[str]:
    """Applique les migrations manquantes, dans l'ordre du nom de fichier.

    Erreur bruyante si le répertoire est introuvable : sans ce garde-fou, un
    chemin erroné donne « 0 migration appliquée », un code de sortie 0, une
    base vide, et rien pour relier les trois.
    """
    if not migrations_dir.is_dir():
        raise MigrationsNotFound(f"répertoire de migrations introuvable : {migrations_dir}")
    if not any(migrations_dir.glob("*.sql")):
        raise MigrationsNotFound(f"aucun fichier .sql dans {migrations_dir}")

    await conn.execute(_MIGRATIONS_TABLE)

    async with conn.cursor() as cur:
        await cur.execute("select version from public.schema_migrations")
        applied = {row[0] for row in await cur.fetchall()}

    pending = sorted(p for p in migrations_dir.glob("*.sql") if p.stem not in applied)
    for path in pending:
        log.info("migration %s", path.stem)
        async with conn.transaction():
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute(
                "insert into public.schema_migrations (version) values (%s)", (path.stem,)
            )
    return [p.stem for p in pending]
