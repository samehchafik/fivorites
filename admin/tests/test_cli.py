"""La ligne de commande, sur les états où l'on se trompe le plus.

Un déploiement neuf passe forcément par « la base est là, le schéma de
l'administration n'y est pas encore ». Ce que la CLI dit à ce moment-là décide
si on perd trente secondes ou une demi-heure.
"""

from __future__ import annotations

import psycopg
import pytest
from typer.testing import CliRunner

from conftest import TEST_DSN, requires_db
from fiv_admin.cli import app

pytestmark = requires_db

runner = CliRunner()


@pytest.fixture(autouse=True)
def _target_the_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    # `get_settings` est mis en cache : sans ça, la première lecture de
    # l'environnement gagnerait pour toute la session de tests.
    from fiv_admin.config import get_settings

    get_settings.cache_clear()


def test_user_add_says_what_to_run_when_the_schema_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'état d'un premier déploiement. Avant, on tombait sur une trace
    `UndefinedTable` : elle dit quelle table manque, pas quoi faire."""
    monkeypatch.setenv("ADMIN_SCHEMA", "schema_jamais_migre")

    result = runner.invoke(app, ["user", "add", "quelquun"])

    assert result.exit_code == 1
    assert "n'existe pas encore" in result.output
    assert "db migrate" in result.output
    # Et surtout : aucune invite de mot de passe. Se le faire saisir deux fois
    # pour rien est précisément ce que le contrôle en amont évite.
    assert "Mot de passe" not in result.output


def test_user_add_creates_then_refuses_a_duplicate(conn: psycopg.AsyncConnection) -> None:
    """Le chemin nominal, et le doublon qui renvoie vers `passwd`."""
    entree = "mot de passe long\nmot de passe long\n"
    created = runner.invoke(app, ["user", "add", "sameh"], input=entree)
    assert created.exit_code == 0, created.output
    assert "créé" in created.output

    again = runner.invoke(app, ["user", "add", "sameh"], input=entree)
    assert again.exit_code == 1
    assert "existe déjà" in again.output
    assert "user passwd sameh" in again.output


def test_a_short_password_is_refused_before_touching_the_base(
    conn: psycopg.AsyncConnection,
) -> None:
    result = runner.invoke(app, ["user", "add", "court"], input="court\ncourt\n")

    assert result.exit_code == 2
    assert "12 caractères" in result.output
