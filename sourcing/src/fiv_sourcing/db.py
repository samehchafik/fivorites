"""Connexion Postgres et exécution des migrations.

Tout est asynchrone : la collecte passe son temps à attendre le réseau, et on ne
veut pas qu'une écriture bloque la boucle pendant que trente requêtes HTTP sont
en vol.

Une seule base pour tout le projet, un schéma par domaine. La connexion pose le
`search_path` une fois pour toutes : le code applicatif écrit `raw_source` sans
préfixe, et changer de schéma reste un réglage, pas une réécriture de SQL. Les
migrations, elles, qualifient tout explicitement — c'est le seul endroit où
l'emplacement doit être sans ambiguïté.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

# L'historique des migrations vaut pour la base entière, pas pour un domaine :
# il vit donc dans `public`, quel que soit le search_path courant.
_MIGRATIONS_TABLE = """
create table if not exists public.schema_migrations (
    version    text        primary key,
    applied_at timestamptz not null default now()
)
"""


@asynccontextmanager
async def connect(dsn: str, *, schema: str | None = None) -> AsyncIterator[psycopg.AsyncConnection]:
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    try:
        if schema:
            await conn.execute(
                sql.SQL("set search_path to {}, public").format(sql.Identifier(schema))
            )
        yield conn
    finally:
        await conn.close()


class MigrationsNotFound(RuntimeError):
    """Le répertoire de migrations est absent ou vide."""


async def pending_migrations(conn: psycopg.AsyncConnection, migrations_dir: Path) -> list[str]:
    """Migrations présentes sur disque et pas encore appliquées.

    Sert de garde-fou aux commandes de traitement par lots. Sans lui, une
    migration oubliée se manifeste par une trace psycopg au milieu d'une passe —
    `column c.first_air_date does not exist` — qui ne dit pas quoi faire. Le cas
    est fréquent sur le serveur, où le code arrive par `git pull` et les
    migrations par une reconstruction d'image : les deux peuvent diverger.
    """
    if not migrations_dir.is_dir():
        raise MigrationsNotFound(f"répertoire de migrations introuvable : {migrations_dir}")

    async with conn.cursor() as cur:
        await cur.execute("select to_regclass('public.schema_migrations') is not null")
        row = await cur.fetchone()
        applied: set[str] = set()
        if row and row[0]:
            await cur.execute("select version from public.schema_migrations")
            applied = {r[0] for r in await cur.fetchall()}

    return sorted(p.stem for p in migrations_dir.glob("*.sql") if p.stem not in applied)


async def migrate(conn: psycopg.AsyncConnection, migrations_dir: Path) -> list[str]:
    """Applique les migrations manquantes, dans l'ordre du nom de fichier.

    Chaque fichier est joué dans sa propre transaction et enregistré dans le
    même commit : une migration qui échoue à mi-parcours n'est jamais marquée
    comme appliquée.

    Lève `MigrationsNotFound` si le répertoire est introuvable ou ne contient
    aucun `.sql`. Sans ce garde-fou, un chemin erroné — cas typique d'une image
    mal construite, où `migrations/` n'a pas été copié — se traduirait par
    « 0 migration appliquée » et un code de sortie 0 : un succès apparent, une
    base vide, et rien pour relier les deux.
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


async def ping(conn: psycopg.AsyncConnection) -> str:
    async with conn.cursor() as cur:
        await cur.execute("select version()")
        row = await cur.fetchone()
    return row[0] if row else "?"
