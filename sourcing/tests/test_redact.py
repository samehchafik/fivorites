"""Aucun secret ne doit sortir dans un affichage ou un journal.

Cas réel à l'origine de ces tests : une clé TMDB v3 apparaissait en clair dans
chaque ligne de log de httpx, qui journalise l'URL complète de ses requêtes.
"""

from __future__ import annotations

import logging

import pytest

from fiv_sourcing.redact import SecretFilter, fingerprint, redact_dsn, redact_secrets

CLE = "b2788d431e93532f095b33ea23721262"
EMPREINTE = "b2788.....23721262"

URL_TMDB = f"https://api.themoviedb.org/3/tv/217/season/21?language=ar-SA&api_key={CLE}"


def test_l_empreinte_identifie_la_cle_sans_la_livrer():
    """Reconnaître quelle clé est chargée — après une rotation, entre deux
    environnements — sans qu'elle soit réutilisable : sur 32 caractères
    hexadécimaux, 19 restent inconnus."""
    assert fingerprint(CLE) == EMPREINTE
    assert CLE not in fingerprint(CLE)


def test_un_secret_court_est_masque_entierement():
    """Une empreinte sur un secret court en révélerait la majeure partie."""
    assert fingerprint("court") == "***"
    assert fingerprint("a" * 20) == "***"
    assert fingerprint("a" * 21) != "***"


def test_la_cle_api_est_remplacee_par_son_empreinte_dans_une_url():
    masque = redact_secrets(URL_TMDB)
    assert CLE not in masque
    assert f"api_key={EMPREINTE}" in masque
    assert "language=ar-SA" in masque, "le reste de l'URL doit rester lisible"


@pytest.mark.parametrize(
    "parametre", ["api_key", "apikey", "API_KEY", "access_token", "session_id", "token"]
)
def test_les_noms_usuels_sont_couverts(parametre: str):
    assert (
        redact_secrets(f"https://h/x?{parametre}={CLE}") == f"https://h/x?{parametre}={EMPREINTE}"
    )


@pytest.mark.parametrize("parametre", ["password", "passwd", "secret"])
def test_un_mot_de_passe_est_masque_en_entier_meme_s_il_est_long(parametre: str):
    """Contrairement à une clé tirée au hasard, un mot de passe est choisi par
    un humain : souvent structuré, donc devinable à partir d'un fragment."""
    assert redact_secrets(f"https://h/x?{parametre}={CLE}") == f"https://h/x?{parametre}=***"


def test_un_parametre_suivi_d_un_autre_est_masque_sans_deborder():
    masque = redact_secrets(f"https://h/x?api_key={CLE}&page=2")
    assert masque == f"https://h/x?api_key={EMPREINTE}&page=2"


def test_le_filtre_masque_les_messages_de_bibliotheques_tierces():
    """La fuite venait de httpx : le filtre doit agir sans que le module
    fautif soit connu à l'avance."""
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='HTTP Request: GET %s "HTTP/1.1 200 OK"',
        args=(URL_TMDB,),
        exc_info=None,
    )

    SecretFilter().filter(record)

    assert CLE not in record.getMessage()
    assert f"api_key={EMPREINTE}" in record.getMessage()


def test_le_filtre_laisse_passer_les_messages_sans_secret():
    record = logging.LogRecord(
        name="fiv_sourcing.db",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="migration %s",
        args=("001_sourcing",),
        exc_info=None,
    )

    assert SecretFilter().filter(record) is True
    assert record.getMessage() == "migration 001_sourcing"


@pytest.mark.parametrize(
    ("dsn", "attendu"),
    [
        (
            "postgresql://fivorites_v2:s3cr3t@172.28.0.1:5432/fivorites_v2",
            "postgresql://fivorites_v2:***@172.28.0.1:5432/fivorites_v2",
        ),
        (
            "postgresql://fivorites_v2@localhost:5432/fivorites_v2",
            "postgresql://fivorites_v2@localhost:5432/fivorites_v2",
        ),
        ("postgresql://h/db?password=s3cr3t&sslmode=require", "postgresql://h/db"),
    ],
)
def test_le_mot_de_passe_de_connexion_ne_ressort_jamais(dsn: str, attendu: str):
    assert redact_dsn(dsn) == attendu


def test_une_chaine_non_url_est_rendue_telle_quelle():
    """psycopg accepte aussi la forme `key=value`, qu'on ne cherche pas à
    interpréter — mais elle ne doit pas faire planter l'affichage."""
    assert redact_dsn("dbname=fivorites_v2 user=fivorites_v2") == (
        "dbname=fivorites_v2 user=fivorites_v2"
    )
