from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

from fiv_sourcing.config import Settings
from fiv_sourcing.db import migrate


def test_dsn(dsn: str) -> str:
    """Même serveur, base suffixée `_test`.

    Les tests vident les tables entre chaque cas : les laisser pointer sur la
    base de travail détruirait le catalogue à chaque `make test`. C'est arrivé
    une fois — 228 000 séries à re-télécharger — d'où cette séparation.
    """
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "_test"))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=test_dsn(Settings().database_url),
        tmdb_bearer="jeton-de-test",
        tmdb_api_key="",
        tmdb_rate_limit=0,  # pas de bridage en test
        http_max_attempts=3,
    )


@pytest.fixture
async def conn(settings: Settings):
    """Connexion à la base de test, migrée et vidée."""
    try:
        connection = await asyncio.wait_for(
            psycopg.AsyncConnection.connect(settings.database_url, autocommit=True),
            timeout=3,
        )
    except (psycopg.Error, OSError, TimeoutError) as exc:
        pytest.skip(f"base de test indisponible ({exc}) — lancer `make db-create`")

    try:
        # Les migrations créent le schéma ; le search_path ne peut être posé
        # qu'après, sinon la toute première exécution pointe dans le vide.
        await migrate(connection, settings.migrations_dir)
        await connection.execute(
            sql.SQL("set search_path to {}, public").format(sql.Identifier(settings.db_schema))
        )
        # `riche_source`, `oeuvre`, `video` et `video_scan` référencent
        # `raw_source` et `tmdb_catalog` : un truncate qui les oublierait
        # échouerait sur la contrainte.
        await connection.execute(
            "truncate raw_source, fetch_state, tmdb_catalog, riche_source, oeuvre,"
            " video, video_scan,"
            # Depuis la migration 013, les tables `membre` rangent tops,
            # découvertes et avis sous `sourcing.oeuvre` : les omettre fait
            # échouer le truncate sur la contrainte, et toute la suite avec.
            " membre.membre, membre.identifiant, membre.oeuvre_v1, membre.five,"
            " membre.five_position, membre.decouverte, membre.avis"
        )
        yield connection
    finally:
        await connection.close()
