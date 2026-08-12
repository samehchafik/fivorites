"""La projection de volume de `tmdb stats`, et le piège qu'elle a tendu.

Le 2026-08-12, sur le serveur : 500 films collectés à côté de 228 000 séries.
La commande a annoncé **28,6 Mo par film** et **33,6 To** pour le catalogue.
Le vrai chiffre est de l'ordre de 100 Ko et 120 Go — faux d'un facteur 430, et
assez effrayant pour dissuader de lancer la passe.

La cause : `pg_total_relation_size('raw_source')` mesure la table entière, tous
univers confondus, et elle était divisée par le nombre d'œuvres du seul univers
demandé. Autrement dit, le poids des séries était imputé aux films.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fiv_sourcing.univers import FILMS, SERIES, kinds_de


def test_chaque_univers_declare_les_kinds_qu_il_alimente() -> None:
    """Une série pèse sur deux `kind` — sa fiche et ses saisons — et les deux
    comptent quand on mesure ce qu'elle occupe."""
    assert kinds_de(SERIES) == ("tv", "tv_season")
    assert kinds_de(FILMS) == ("movie",)


def test_le_poids_d_un_univers_n_emprunte_rien_a_l_autre() -> None:
    """Le calcul de la projection, isolé de la base — c'est l'arithmétique qui
    était fausse, pas la requête.

    Les valeurs sont celles relevées sur le serveur, arrondies au Mo.
    """
    mo = 1024**2
    rows = [
        ("movie", 500, 500, 33 * mo),
        ("tv", 228_474, 228_454, 2_923 * mo),
        ("tv_season", 1_957_510, 391_196, 6_412 * mo),
    ]
    sur_disque = 14.0 * 1024**3  # pg_total_relation_size de la table entière

    payloads = sum(r[3] for r in rows)
    surcout = sur_disque / payloads

    mien = set(kinds_de(FILMS))
    octets_films = sum(r[3] for r in rows if r[0] in mien)
    par_film = octets_films / 500 * surcout

    assert 80_000 < par_film < 130_000, "de l'ordre de 100 Ko, pas de 28 Mo"
    projection = par_film * 1_231_681
    assert projection < 200 * 1024**3, "de l'ordre de 120 Go, pas de 33 To"

    # Et le contrôle qui dit que la correction porte bien : l'ancienne formule.
    ancienne = sur_disque / 500
    assert ancienne / par_film > 100, "l'écart que ce test existe pour empêcher"


@pytest.mark.integration
async def test_les_deux_univers_pesent_separement_en_base(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le même fait, vérifié contre Postgres : la somme par `kind` sépare bien
    les univers, ce sur quoi repose tout le calcul ci-dessus."""
    for kind, source_id, taille in (
        ("movie", "550", 400),
        ("tv", "1399", 100),
        ("tv_season", "1399/s1", 100),
    ):
        await conn.execute(
            "insert into raw_source (source, kind, source_id, http_status, payload,"
            " payload_sha256) values ('tmdb', %s, %s, 200, %s, sha256(%s::bytea))",
            (kind, source_id, Jsonb({"x": "y" * taille}), source_id.encode()),
        )

    async with conn.cursor() as cur:
        await cur.execute(
            "select kind, sum(pg_column_size(payload))::bigint from raw_source"
            " where source = 'tmdb' group by kind"
        )
        poids = dict(await cur.fetchall())

    films = sum(poids.get(k, 0) for k in kinds_de(FILMS))
    series = sum(poids.get(k, 0) for k in kinds_de(SERIES))
    assert films > 0 and series > 0
    assert films + series == sum(poids.values()), "aucun kind ne compte deux fois"
    assert films > series, "le film de ce jeu est plus gros que la série et ses saisons"
