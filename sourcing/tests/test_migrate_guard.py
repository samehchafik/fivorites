"""Le cas « rien ne s'est passé, et personne ne l'a dit ».

Un répertoire de migrations absent ou vide doit être une erreur bruyante. Sinon
une image mal construite — `migrations/` non copié — produit un code de sortie 0
sur une base restée vide, et rien ne relie les deux.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fiv_sourcing.db import MigrationsNotFound, migrate

pytestmark = pytest.mark.integration


async def test_repertoire_absent(conn, tmp_path: Path):
    with pytest.raises(MigrationsNotFound, match="introuvable"):
        await migrate(conn, tmp_path / "nexiste_pas")


async def test_repertoire_vide(conn, tmp_path: Path):
    with pytest.raises(MigrationsNotFound, match="aucun fichier"):
        await migrate(conn, tmp_path)


async def test_repertoire_sans_sql(conn, tmp_path: Path):
    (tmp_path / "notes.txt").write_text("pas une migration")
    with pytest.raises(MigrationsNotFound, match="aucun fichier"):
        await migrate(conn, tmp_path)


async def test_les_migrations_en_attente_sont_listees(conn, settings, tmp_path):
    """Le garde-fou des passes par lots : une migration sur disque et pas en
    base doit être nommée, pas découverte au milieu d'une passe par un
    `column ... does not exist`."""
    from fiv_sourcing.db import pending_migrations

    (tmp_path / "001_sourcing.sql").write_text("select 1")
    (tmp_path / "999_pas_encore.sql").write_text("select 1")

    attente = await pending_migrations(conn, tmp_path)

    assert attente == ["999_pas_encore"], "001 est déjà appliquée par la fixture"


async def test_un_schema_a_jour_ne_signale_rien(conn, settings, tmp_path):
    from fiv_sourcing.db import pending_migrations

    for chemin in settings.migrations_dir.glob("*.sql"):
        (tmp_path / chemin.name).write_text("select 1")

    assert await pending_migrations(conn, tmp_path) == []
