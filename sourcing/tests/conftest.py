from __future__ import annotations

import asyncio

import psycopg
import pytest
from psycopg import sql

from fiv_sourcing.config import Settings
from fiv_sourcing.db import migrate


@pytest.fixture
def settings() -> Settings:
    return Settings(
        tmdb_bearer="jeton-de-test",
        tmdb_api_key="",
        tmdb_rate_limit=0,  # pas de bridage en test
        http_max_attempts=3,
    )


@pytest.fixture
async def conn(settings: Settings):
    """Connexion à la base de test, migrée et vidée.

    Le test est ignoré si Postgres n'est pas là : `make db-create` pour l'activer.
    """
    try:
        connection = await asyncio.wait_for(
            psycopg.AsyncConnection.connect(settings.database_url, autocommit=True),
            timeout=3,
        )
    except (psycopg.Error, OSError, TimeoutError) as exc:
        pytest.skip(f"Postgres indisponible ({exc}) — lancer `make db-create`")

    try:
        # Les migrations créent le schéma ; le search_path ne peut être posé
        # qu'après, sinon la toute première exécution pointe dans le vide.
        await migrate(connection, settings.migrations_dir)
        await connection.execute(
            sql.SQL("set search_path to {}, public").format(sql.Identifier(settings.db_schema))
        )
        await connection.execute("truncate raw_source, fetch_state")
        yield connection
    finally:
        await connection.close()
