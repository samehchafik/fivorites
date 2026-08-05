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
