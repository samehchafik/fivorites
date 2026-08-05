from __future__ import annotations

import pytest

from fiv_sourcing.dsn import redact_dsn


@pytest.mark.parametrize(
    ("dsn", "attendu"),
    [
        (
            "postgresql://fivorites_v2:s3cr3t@172.28.0.1:5432/fivorites_v2",
            "postgresql://fivorites_v2:***@172.28.0.1:5432/fivorites_v2",
        ),
        # Sans mot de passe (auth locale) : rien à masquer.
        (
            "postgresql://fivorites_v2@localhost:5432/fivorites_v2",
            "postgresql://fivorites_v2@localhost:5432/fivorites_v2",
        ),
        # Les paramètres de requête peuvent porter un mot de passe : on les
        # coupe plutôt que de tenter de les filtrer un par un.
        (
            "postgresql://h/db?password=s3cr3t&sslmode=require",
            "postgresql://h/db",
        ),
    ],
)
def test_le_mot_de_passe_ne_ressort_jamais(dsn: str, attendu: str):
    assert redact_dsn(dsn) == attendu


def test_une_chaine_non_url_est_rendue_telle_quelle():
    """psycopg accepte aussi la forme `key=value`, qu'on ne cherche pas à
    interpréter — mais elle ne doit pas faire planter l'affichage."""
    assert redact_dsn("dbname=fivorites_v2 user=fivorites_v2") == (
        "dbname=fivorites_v2 user=fivorites_v2"
    )
