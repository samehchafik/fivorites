"""Le canal vidéo : extraction depuis le brut, et projection en base."""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fiv_sourcing.video import bilan, extraire, projeter_serie, series_a_projeter


def video(cle: str, **surcharges):
    base = {
        "key": cle,
        "site": "YouTube",
        "type": "Trailer",
        "name": f"Bande-annonce {cle}",
        "iso_639_1": "en",
        "official": True,
        "published_at": "2019-04-01T12:00:00.000Z",
        "size": 1080,
    }
    return base | surcharges


def test_extraire_une_fiche_sans_video_ne_casse_rien() -> None:
    """Les trois formes que prend l'absence, et qui arrivent toutes."""
    assert extraire(None) == []
    assert extraire({}) == []
    assert extraire({"videos": {"results": []}}) == []
    assert extraire({"videos": None}) == []


def test_extraire_normalise_les_champs() -> None:
    [v] = extraire({"videos": {"results": [video("abc")]}})
    assert v["site"] == "YouTube"
    assert v["cle"] == "abc"
    assert v["type"] == "Trailer"
    assert v["officiel"] is True
    assert v["definition"] == 1080
    assert v["publie_le"] is not None, "le Z final ne doit pas faire échouer la date"
    assert v["saison"] is None


def test_extraire_ignore_ce_qui_est_inexploitable() -> None:
    """Sans hébergeur ou sans clé, l'URL ne peut pas être reconstruite : la
    ligne n'aurait aucun usage et occuperait une clé primaire."""
    res = extraire(
        {
            "videos": {
                "results": [
                    video("bon"),
                    {"site": "YouTube"},  # pas de clé
                    {"key": "orphelin"},  # pas de site
                    "pas un objet",
                ]
            }
        }
    )
    assert [v["cle"] for v in res] == ["bon"]


def test_extraire_tolere_une_date_absurde() -> None:
    [v] = extraire({"videos": {"results": [video("abc", published_at="hier")]}})
    assert v["publie_le"] is None, "une date illisible vaut mieux qu'une exception"


async def seed(conn: psycopg.AsyncConnection, id_tmdb: int, payload: dict, *, saisons=()) -> None:
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, adult, exported_on)"
        " values (%s, 'Serie', 10, false, current_date)",
        (id_tmdb,),
    )
    await conn.execute(
        "insert into raw_source (source, kind, source_id, http_status, payload, payload_sha256)"
        " values ('tmdb', 'tv', %s, 200, %s, %s)",
        (str(id_tmdb), Jsonb(payload), b"sha-serie"),
    )
    for numero, charge in saisons:
        await conn.execute(
            "insert into raw_source (source, kind, source_id, http_status, payload, payload_sha256)"
            " values ('tmdb', 'tv_season', %s, 200, %s, %s)",
            (f"{id_tmdb}/s{numero}", Jsonb(charge), f"sha-s{numero}".encode()),
        )


async def test_projeter_ecrit_les_videos_et_marque_la_serie(conn) -> None:
    await seed(conn, 1399, {"videos": {"results": [video("a"), video("b", type="Teaser")]}})

    assert await projeter_serie(conn, 1399) == 2

    async with conn.cursor() as cur:
        await cur.execute("select cle, type, priorite from video order by priorite")
        assert await cur.fetchall() == [("a", "Trailer", 0), ("b", "Teaser", 2)], (
            "la bande-annonce officielle passe devant le teaser"
        )
        await cur.execute("select videos from video_scan where id_tmdb = 1399")
        assert await cur.fetchone() == (2,)


async def test_une_serie_sans_video_est_marquee_quand_meme(conn) -> None:
    """Le cas fréquent, et celui qui ferait boucler la passe indéfiniment si on
    ne gardait pas trace de l'examen."""
    await seed(conn, 1400, {"videos": {"results": []}})

    assert await projeter_serie(conn, 1400) == 0

    async with conn.cursor() as cur:
        await cur.execute("select videos from video_scan where id_tmdb = 1400")
        assert await cur.fetchone() == (0,)
    assert await series_a_projeter(conn) == [], "elle ne doit pas revenir à la passe suivante"


async def test_les_saisons_apportent_leurs_videos(conn) -> None:
    await seed(
        conn,
        1401,
        {"videos": {"results": [video("serie")]}},
        saisons=[(2, {"videos": {"results": [video("saison2")]}})],
    )

    assert await projeter_serie(conn, 1401) == 2
    async with conn.cursor() as cur:
        await cur.execute("select cle, saison from video order by cle")
        assert await cur.fetchall() == [("saison2", 2), ("serie", None)]


async def test_la_meme_video_aux_deux_niveaux_ne_fait_quune_ligne(conn) -> None:
    """TMDB liste souvent la bande-annonce de la série sur ses saisons aussi."""
    await seed(
        conn,
        1402,
        {"videos": {"results": [video("commune")]}},
        saisons=[(1, {"videos": {"results": [video("commune")]}})],
    )

    assert await projeter_serie(conn, 1402) == 1
    async with conn.cursor() as cur:
        await cur.execute("select saison from video where cle = 'commune'")
        assert await cur.fetchone() == (None,), "le rattachement de la première vue l'emporte"


async def test_rejouer_ne_duplique_pas(conn) -> None:
    await seed(conn, 1403, {"videos": {"results": [video("a")]}})
    await projeter_serie(conn, 1403)
    await projeter_serie(conn, 1403)

    async with conn.cursor() as cur:
        await cur.execute("select count(*) from video where id_tmdb = 1403")
        assert await cur.fetchone() == (1,)


async def test_une_serie_non_collectee_nest_pas_marquee(conn) -> None:
    """Marquer une série qu'on n'a jamais pu lire prétendrait l'avoir examinée,
    et l'exclurait des passes suivantes une fois collectée."""
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, adult, exported_on)"
        " values (1404, 'Jamais collectee', 10, false, current_date)"
    )

    assert await projeter_serie(conn, 1404) == 0
    async with conn.cursor() as cur:
        await cur.execute("select count(*) from video_scan where id_tmdb = 1404")
        assert await cur.fetchone() == (0,)


async def test_la_selection_ignore_les_series_sans_brut(conn) -> None:
    await seed(conn, 1405, {"videos": {"results": []}})
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, adult, exported_on)"
        " values (1406, 'Sans brut', 99, false, current_date)"
    )

    assert await series_a_projeter(conn) == [1405], "1406 est au catalogue mais jamais collectée"


async def test_tout_reprend_les_series_deja_examinees(conn) -> None:
    await seed(conn, 1407, {"videos": {"results": [video("a")]}})
    await projeter_serie(conn, 1407)

    assert await series_a_projeter(conn) == []
    assert await series_a_projeter(conn, tout=True) == [1407]


async def test_un_ordre_inconnu_est_refuse(conn) -> None:
    """Le nom de l'ordre entre dans le SQL : il ne peut pas venir tel quel de
    la ligne de commande."""
    with pytest.raises(ValueError, match="ordre inconnu"):
        await series_a_projeter(conn, order="; drop table video")


async def test_le_bilan_compte_ce_qui_est_couvert(conn) -> None:
    await seed(
        conn,
        1408,
        {
            "videos": {
                "results": [
                    video("a"),
                    video("fr", iso_639_1="fr", official=False, type="Clip"),
                ]
            }
        },
    )
    await projeter_serie(conn, 1408)

    etat = await bilan(conn)
    assert etat == {
        "examinees": 1,
        "avec_video": 1,
        "videos": 2,
        "annonces_officielles": 1,
        "series_en_francais": 1,
    }
