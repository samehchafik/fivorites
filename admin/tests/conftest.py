"""Fixtures des tests.

Les tests d'intégration tournent sur `fivorites_v2_test`, **jamais** sur la base
de travail : ils vident les tables entre chaque cas, et un `make test` lancé sur
la mauvaise base effacerait un catalogue de 228 000 séries. C'est déjà arrivé
une fois côté sourcing, la leçon est reprise ici telle quelle.

Le schéma vient des migrations réelles — celles de `sourcing` d'abord (l'admin
lit ses tables), puis celles de l'admin. Un jeu de fixtures qui recréerait les
tables à la main finirait par diverger du schéma sans que rien ne le signale.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio

from fiv_admin.config import PROJECT_ROOT, Settings
from fiv_admin.db import migrate
from fiv_admin.embed import MODEL_NAME

# Une base à l'administration seule, distincte de `fivorites_v2_test` où
# `sourcing` fait tourner la sienne.
#
# Elles la partageaient, et ça a fini par se voir : deux suites lancées en
# parallèle se tronquent mutuellement les tables entre deux assertions, et une
# base réinitialisée d'un côté fait disparaître de `schema_migrations` les
# migrations de l'autre — qui tente alors de recréer des tables existantes.
# Le schéma de `sourcing` est reconstruit ici depuis ses propres migrations :
# rien n'est perdu, seule l'isolation est gagnée.
TEST_DSN = os.environ.get(
    "ADMIN_TEST_DATABASE_URL",
    "postgresql://fivorites_v2@localhost:5432/fivorites_v2_admin_test",
)

SOURCING_MIGRATIONS = PROJECT_ROOT.parent / "sourcing" / "migrations"
ADMIN_MIGRATIONS = PROJECT_ROOT / "migrations"


def _reachable() -> bool:
    try:
        with psycopg.connect(TEST_DSN, connect_timeout=2) as conn:
            conn.execute("select 1")
    except Exception:  # noqa: BLE001 — l'absence de base n'est pas un échec de test
        return False
    return True


requires_db = pytest.mark.skipif(
    not _reachable(),
    reason=f"Postgres de test injoignable ({TEST_DSN}) — `make -C ../sourcing db-create`",
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url=TEST_DSN,
        admin_secret_key="secret-de-test-sans-valeur",
        migrations_dir=ADMIN_MIGRATIONS,
        web_dist=Path("/inexistant"),
        cors_origins="",
        summary_cache_seconds=0,
        # Encodeur local pour la suite : la production appelle une API, et un
        # test qui en dependrait mesurerait le reseau. Sans cle le secours
        # prendrait le relais, mais l'entrainement ecarte les vecteurs de
        # secours — a raison — et la suite ne testerait plus rien.
        embedder=MODEL_NAME,
    )


@pytest_asyncio.fixture
async def conn(settings: Settings) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(
        settings.database_url, autocommit=True
    ) as connection:
        await migrate(connection, SOURCING_MIGRATIONS)
        await migrate(connection, ADMIN_MIGRATIONS)
        # `sourcing.riche_source` référence `raw_source` et `tmdb_catalog` :
        # l'omettre ferait échouer le truncate sur la contrainte, dans un test
        # qui n'a rien à voir. Les tables de notation référencent tmdb_catalog
        # et rubric : mêmes obligations.
        await connection.execute(
            "truncate sourcing.raw_source, sourcing.fetch_state, sourcing.tmdb_catalog,"
            " sourcing.riche_source, sourcing.oeuvre, sourcing.video, sourcing.video_scan,"
            " admin.admin_user,"
            " notation.score, notation.weights, notation.embedding, notation.media_caption,"
            " notation.training_run, notation.training_weights"
        )
        # Les barèmes de test disparaissent, le `v1` semé par la migration
        # reste : c'est lui que la page d'entraînement propose par défaut.
        await connection.execute("delete from notation.rubric where version <> 'v1'")
        await connection.execute("set search_path to sourcing, admin, public")
        yield connection
