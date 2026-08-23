"""Connexion Postgres, pool et migrations.

Le `search_path` est posé une fois par connexion — `sourcing`, `admin`,
`visiteur`, puis `public`. Le code applicatif lit donc `oeuvre` et `tv_card`
sans préfixe et écrit `visiteur.signal` qualifié — le préfixe sur notre propre
schéma dit qu'on écrit, comme le préfixe `membre.` de l'admin dit qu'on lit
chez le voisin.

Ce module reprend la mécanique de `fiv_admin.db`, qui reprenait celle de
`fiv_sourcing.db`. Le triplement est assumé, pour la même raison que le
doublement l'était : les modules se déploient séparément, et les coupler pour
une quarantaine de lignes créerait une dépendance d'image entre trois services
qui n'ont rien d'autre à partager.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
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
        # Même garde-fou que les deux autres modules : un client tué net au
        # milieu d'une transaction laisse une session zombie qui tient ses
        # verrous. Postgres la tue lui-même passé ce délai.
        await conn.execute("set idle_in_transaction_session_timeout = '5min'")
        if schemas:
            await conn.execute(search_path(*schemas))
        yield conn
    finally:
        await conn.close()


async def _poser_search_path(schemas: tuple[str, ...], conn: psycopg.AsyncConnection) -> None:
    await conn.execute(search_path(*schemas))


def build_pool(dsn: str, *schemas: str, max_size: int = 8) -> AsyncConnectionPool:
    """Pool du service web. Ouvert par le cycle de vie de l'application.

    `open=False` : le pool ne se connecte qu'au démarrage de l'application, pas
    à l'import — sinon les tests et `--help` tenteraient une connexion.
    """
    return AsyncConnectionPool(
        dsn,
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True},
        configure=partial(_poser_search_path, schemas) if schemas else None,
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
