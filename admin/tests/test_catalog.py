"""La grille de vignettes, la fiche et les saisons.

Le jeu de données est un brut réaliste : c'est la seule façon de vérifier qu'on
lit les bons chemins du payload TMDB — `aggregate_credits.cast[].roles[]`,
`images.backdrops[]`, `seasons[]`, `episodes[]` — sans avoir à collecter pour de
vrai.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from conftest import requires_db
from fiv_admin.catalog import (
    EXTRAIT_CHARS,
    CardQuery,
    cards_state,
    fetch_cards,
    fetch_rich,
    fetch_season,
    fetch_work,
    refresh_cards,
)

pytestmark = [pytest.mark.integration, requires_db]


SERIES_1399 = {
    "id": 1399,
    "name": "Le Trône de fer",
    "original_name": "Game of Thrones",
    "overview": "Neuf familles nobles se disputent le contrôle de Westeros.",
    "tagline": "L'hiver vient",
    "poster_path": "/got.jpg",
    "backdrop_path": "/got-large.jpg",
    "first_air_date": "2011-04-17",
    "last_air_date": "2019-05-19",
    "number_of_seasons": 2,
    "number_of_episodes": 20,
    "vote_average": 8.4,
    "vote_count": 22000,
    "status": "Ended",
    "type": "Scripted",
    "original_language": "en",
    "origin_country": ["US"],
    "homepage": "https://exemple.test/got",
    "genres": [{"id": 1, "name": "Drame"}, {"id": 2, "name": "Fantastique"}],
    "networks": [{"id": 49, "name": "HBO", "logo_path": "/hbo.png"}],
    "created_by": [{"id": 9, "name": "David Benioff"}],
    "external_ids": {"imdb_id": "tt0944947", "wikidata_id": "Q23572"},
    "seasons": [
        {
            "season_number": 1,
            "name": "Saison 1",
            "air_date": "2011-04-17",
            "episode_count": 10,
            "poster_path": "/s1.jpg",
            "overview": "",
        },
        {
            "season_number": 2,
            "name": "Saison 2",
            "air_date": "2012-04-01",
            "episode_count": 10,
            "poster_path": "/s2.jpg",
            "overview": "",
        },
    ],
    "images": {
        # Vingt-cinq visuels : la troncature en SQL doit en garder dix-huit.
        "backdrops": [{"file_path": f"/backdrop-{index}.jpg"} for index in range(25)],
        "posters": [{"file_path": f"/poster-{index}.jpg"} for index in range(4)],
    },
    "aggregate_credits": {
        "cast": [
            {
                "id": 100 + index,
                "name": f"Comédien {index}",
                "profile_path": f"/face-{index}.jpg",
                "total_episode_count": 60 - index,
                "roles": [{"character": f"Personnage {index}", "episode_count": 60 - index}],
            }
            for index in range(40)
        ]
    },
    "translations": {
        "translations": [
            # Reproduit ce que TMDB renvoie réellement : un `name` vide veut
            # dire « pas de titre localisé », et chaque champ peut venir d'une
            # région différente de la même langue. Sur la vraie fiche 1399, le
            # titre français vient de fr-CA et le synopsis de fr-FR.
            {"iso_639_1": "fr", "iso_3166_1": "CA", "data": {"name": "Le trône de fer"}},
            {
                "iso_639_1": "de",
                "iso_3166_1": "DE",
                "data": {"name": "", "overview": "Die Handlung…"},
            },
            {"iso_639_1": "fr", "iso_3166_1": "FR", "data": {}},
            # Deux variantes d'arabe : la requête doit préférer celle dont la
            # région correspond à la langue choisie (ar-SA), pas la première
            # venue — sinon le résultat change d'une collecte à l'autre.
            {
                "iso_639_1": "ar",
                "iso_3166_1": "AE",
                "data": {"name": "عنوان إماراتي", "overview": "ملخص إماراتي"},
            },
            {
                "iso_639_1": "ar",
                "iso_3166_1": "SA",
                "data": {
                    "name": "لعبة العروش",
                    "overview": "تسع عائلات نبيلة تتصارع على ويستروس.",
                    "tagline": "الشتاء قادم",
                },
            },
            # Le turc n'a qu'un titre : le synopsis doit se replier sur le
            # français, et le dire.
            {"iso_639_1": "tr", "iso_3166_1": "TR", "data": {"name": "Taht Oyunları"}},
        ]
    },
    # La forme exacte de TMDB : un dictionnaire par pays, des rubriques par
    # mode d'accès, et un `display_priority` qui donne l'ordre d'affichage.
    "watch/providers": {
        "results": {
            "FR": {
                "link": "https://www.themoviedb.org/tv/1399/watch?locale=FR",
                "flatrate": [
                    {
                        "provider_id": 119,
                        "provider_name": "Prime Video",
                        "logo_path": "/prime.jpg",
                        "display_priority": 3,
                    },
                    {
                        "provider_id": 8,
                        "provider_name": "Netflix",
                        "logo_path": "/netflix.jpg",
                        "display_priority": 1,
                    },
                ],
                "rent": [
                    {
                        "provider_id": 2,
                        "provider_name": "Apple TV",
                        "logo_path": "/apple.jpg",
                        "display_priority": 5,
                    }
                ],
            },
            "SA": {
                "link": "https://www.themoviedb.org/tv/1399/watch?locale=SA",
                "flatrate": [
                    {
                        "provider_id": 350,
                        "provider_name": "Shahid VIP",
                        "logo_path": "/shahid.jpg",
                        "display_priority": 2,
                    }
                ],
            },
        }
    },
}

SERIES_2000 = {
    "id": 2000,
    "name": "باب الحارة",
    "original_name": "باب الحارة",
    "overview": "Chronique d'un quartier de Damas.",
    "poster_path": "/bab.jpg",
    "first_air_date": "2006-09-23",
    "number_of_seasons": 1,
    "number_of_episodes": 31,
    "status": "Ended",
    "original_language": "ar",
    "origin_country": ["SY"],
    "genres": [{"id": 3, "name": "Drame"}],
    "seasons": [
        {"season_number": 1, "name": "الموسم 1", "air_date": "2006-09-23", "episode_count": 31}
    ],
}

SEASON_1_FR = {
    "name": "Saison 1",
    "overview": "La maison Stark.",
    "air_date": "2011-04-17",
    "poster_path": "/s1.jpg",
    "episodes": [
        {
            "episode_number": number,
            "name": f"Épisode {number}",
            "overview": f"Synopsis français de l'épisode {number}.",
            "air_date": "2011-04-17",
            "runtime": 60,
            "still_path": f"/still-{number}.jpg",
            "vote_average": 8.0,
        }
        for number in (1, 2)
    ],
}

SEASON_1_AR = {
    **SEASON_1_FR,
    "name": "الموسم 1",
    "episodes": [
        {**episode, "overview": f"ملخص الحلقة {episode['episode_number']}"}
        for episode in SEASON_1_FR["episodes"]
    ],
}


def pivot(id_tmdb: int) -> str:
    """Le pivot d'une série, en SQL.

    Les tests insèrent notes et vidéos par lots de plusieurs lignes : un
    sous-select se lit mieux qu'un aller-retour en base par ligne, et il dit
    exactement ce que fait le code de production.
    """
    return f"(select id from oeuvre where univers = 'series' and id_tmdb = {id_tmdb})"


async def seed(conn: psycopg.AsyncConnection) -> None:
    await conn.execute(
        """
        insert into tmdb_catalog (id, original_name, popularity, exported_on) values
            (1399, 'Game of Thrones', 400.0, date '2026-08-05'),
            (2000, 'باب الحارة',       11.4, date '2026-08-05'),
            (4000, 'Jamais collectée',  0.1, date '2026-08-05')
        """
    )
    # Le pivot des deux séries collectées : c'est la collecte qui le crée en
    # production (`collect_series`), et c'est par lui que notes et vidéos se
    # rangent depuis le lot 12. 4000 n'en a pas — elle n'est pas collectée.
    await conn.execute(
        "insert into oeuvre (univers, id_tmdb) values ('series', 1399), ('series', 2000)"
    )
    for tv_id, payload, digest in (
        (1399, SERIES_1399, b"\x01"),
        (2000, SERIES_2000, b"\x02"),
    ):
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200, %s::jsonb, %s)
            """,
            (str(tv_id), json.dumps(payload), digest),
        )

    await conn.execute(
        """
        insert into fetch_state (source, kind, source_id, last_fetched_at,
                                 last_success_at, last_status) values
            ('tmdb', 'tv',        '1399',    now(), now(), 200),
            ('tmdb', 'tv',        '2000',    now(), now(), 200),
            ('tmdb', 'tv_season', '1399/s1', now(), now(), 200),
            ('tmdb', 'tv_season', '1399/s2', now(), now(), 200)
        """
    )
    for source_id, lang, payload, status, digest in (
        ("1399/s1", "fr-FR", SEASON_1_FR, 200, b"\x11"),
        ("1399/s1", "ar-SA", SEASON_1_AR, 200, b"\x12"),
        ("1399/s2", "fr-FR", {"episodes": []}, 200, b"\x13"),
        ("1399/s2", "ar-SA", None, 404, b"\x14"),
    ):
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv_season', %s, %s, %s, %s::jsonb, %s)
            """,
            (source_id, lang, status, json.dumps(payload) if payload else None, digest),
        )

    await refresh_cards(conn)


async def test_cards_are_sorted_newest_first(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    rows, total = await fetch_cards(conn, CardQuery(lang="fr-FR"))

    assert total == 2, "seules les séries collectées ont une vignette"
    assert [row["id"] for row in rows] == [1399, 2000]
    assert [row["year"] for row in rows] == [2011, 2006]


async def test_card_carries_what_the_vignette_shows(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR"))
    got = next(row for row in rows if row["id"] == 1399)

    assert got["name"] == "Le Trône de fer"
    assert got["posterPath"] == "/got.jpg"
    assert got["seasons"] == 2
    assert got["year"] == 2011
    assert got["genres"] == ["Drame", "Fantastique"]
    assert got["popularity"] == 400.0
    # Deux saisons énumérées, deux collectées en français.
    assert got["expectedParts"] == 2
    assert got["selected"] == {"lang": "fr-FR", "ok": 2, "failed": 0, "ratio": 1.0}
    assert got["coverage"]["ar-SA"] == {"ok": 1, "failed": 1}
    assert got["axisScores"] is None, "jamais notée : pas de vecteur, pas de zéros"


async def test_card_carries_the_axis_vector_when_scored(conn: psycopg.AsyncConnection) -> None:
    """Le vecteur de goût sur la vignette : le dernier verdict du juge par
    axe — jamais la contre-note manuelle, jamais la prédiction interne."""
    await seed(conn)
    await conn.execute(
        f"""
        insert into notation.score
            (oeuvre_id, axe, valeur, confiance, rubric_version, modele,
             input_sha256, prompt_sha256, scored_at)
        values
            ({pivot(1399)}, 'luminosite', 3, 0.8, 'v1', 'gpt-test',
             'sha-in', 'sha-p', now() - interval '1 day'),
            ({pivot(1399)}, 'luminosite', 4, 0.8, 'v1', 'gpt-test', 'sha-in', 'sha-p', now()),
            ({pivot(1399)}, 'intensite',  9, 0.8, 'v1', 'interne-ridge',
             'sha-in', 'sha-p', now()),
            ({pivot(1399)}, 'humour',     2, 0.8, 'v1', 'claude-web-manuel',
             'sha-in', 'sha-p', now())
        """
    )

    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR"))
    notee = next(row for row in rows if row["id"] == 1399)
    non_notee = next(row for row in rows if row["id"] == 2000)

    assert notee["axisScores"] == {"luminosite": 4.0}, (
        "le plus récent gagne sur luminosite ; intensite et humour n'ont que des "
        "notes exclues (interne, manuelle) et n'apparaissent donc pas"
    )
    assert non_notee["axisScores"] is None


async def test_only_the_current_rubric_shows(conn: psycopg.AsyncConnection) -> None:
    """Changer de référentiel ne fait pas cohabiter deux jeux d'axes.

    `distinct on (id_tmdb, axe)` groupe par *nom* d'axe, et deux barèmes n'ont
    pas les mêmes noms : sans filtre sur la version, une œuvre notée sous
    l'ancien barème et sous le nouveau montrerait les axes des deux empilés —
    un vecteur chimère qui n'existe dans aucun référentiel. Et tant que rien
    n'est noté sous le barème courant, elle montrerait ceux de l'ancien.
    """
    await seed(conn)
    await conn.execute(
        "insert into notation.rubric (version, prompt, axes) values"
        " ('v-suivant', 'p', '[\"joie\"]'::jsonb)"
    )
    await conn.execute(
        f"""
        insert into notation.score
            (oeuvre_id, axe, valeur, confiance, rubric_version, modele,
             input_sha256, prompt_sha256)
        values
            ({pivot(1399)}, 'luminosite', 4, 0.8, 'v1',        'gpt-test', 'sha-in', 'sha-p'),
            ({pivot(1399)}, 'joie',       7, 0.8, 'v-suivant', 'gpt-test', 'sha-in', 'sha-p')
        """
    )

    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR"))
    vignette = next(row for row in rows if row["id"] == 1399)
    fiche = await fetch_work(conn, 1399, lang="fr-FR")

    assert vignette["axisScores"] == {"joie": 7.0}, "l'ancien axe n'a rien à faire là"
    assert fiche["axisScores"] == {"joie": 7.0}, "la fiche suit la même règle"


async def test_the_cards_are_translated_too(conn: psycopg.AsyncConnection) -> None:
    """La grille lit la projection, qui ne stocke que le titre français. Les
    traductions viennent du payload de la fiche, ouvert pour les seules séries
    de la page — jamais pour le catalogue entier."""
    await seed(conn)

    arabe, _ = await fetch_cards(conn, CardQuery(lang="ar-SA"))
    got = next(row for row in arabe if row["id"] == 1399)
    assert got["name"] == "لعبة العروش"
    assert got["overview"].startswith("تسع عائلات")

    francais, _ = await fetch_cards(conn, CardQuery(lang="fr-FR"))
    got = next(row for row in francais if row["id"] == 1399)
    assert got["name"] == "Le Trône de fer"

    # Le turc n'a qu'un titre traduit : le synopsis se replie sur le français,
    # sans mention sur la vignette — c'est la fiche qui l'annonce.
    turc, _ = await fetch_cards(conn, CardQuery(lang="tr-TR"))
    got = next(row for row in turc if row["id"] == 1399)
    assert got["name"] == "Taht Oyunları"
    assert got["overview"].startswith("Neuf familles")

    # Une langue absente des traductions retombe sur le titre **original**, pas
    # sur le français : c'est ce que fait TMDB, et afficher « Le Trône de fer »
    # à un lecteur hispanophone serait le tromper sur deux langues à la fois.
    espagnol, _ = await fetch_cards(conn, CardQuery(lang="es-ES"))
    got = next(row for row in espagnol if row["id"] == 1399)
    assert got["name"] == "Game of Thrones"
    assert got["overview"].startswith("Neuf familles"), "le synopsis, lui, n'a que le français"


async def test_cards_sort_and_search(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)

    oldest, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", descending=False))
    assert [row["id"] for row in oldest] == [2000, 1399]

    # Le tri par titre suit la collation de la base, qui range l'écriture latine
    # avant l'arabe. Ce n'est pas un choix du code : il n'y a pas d'ordre
    # alphabétique commun à deux alphabets, et en inventer un ici tromperait
    # plus qu'il n'aiderait.
    by_name, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="name", descending=False))
    assert [row["id"] for row in by_name] == [1399, 2000]

    found, total = await fetch_cards(conn, CardQuery(lang="fr-FR", search="trône"))
    assert total == 1 and found[0]["id"] == 1399

    # La recherche porte aussi sur le titre original et sur l'id.
    found, total = await fetch_cards(conn, CardQuery(lang="fr-FR", search="Game of"))
    assert total == 1 and found[0]["id"] == 1399
    found, total = await fetch_cards(conn, CardQuery(lang="fr-FR", search="2000"))
    assert total == 1 and found[0]["id"] == 2000


async def test_a_second_criterion_breaks_the_ties(conn: psycopg.AsyncConnection) -> None:
    """« Les plus récentes, et à date égale les plus populaires ».

    Sans départage, un lot de séries sorties le même jour tombe dans un ordre
    arbitraire, qui peut changer d'une page à l'autre — la pagination fait alors
    apparaître deux fois la même série, ou en saute une.
    """
    await seed(conn)
    # Trois séries à la même date, popularités distinctes.
    for tv_id, popularity, digest in (
        (5001, 1.0, b"\x31"),
        (5002, 90.0, b"\x32"),
        (5003, 40.0, b"\x33"),
    ):
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (%s, %s, %s, date '2026-08-05')",
            (tv_id, f"Même jour {tv_id}", popularity),
        )
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200,
                    jsonb_build_object('name', %s::text, 'first_air_date', '2020-01-01'), %s)
            """,
            (str(tv_id), f"Même jour {tv_id}", digest),
        )
    await refresh_cards(conn)

    same_day = [5002, 5003, 5001]  # par popularité décroissante

    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="air_date", sort2="popularity"))
    assert [row["id"] for row in rows if row["id"] in same_day] == same_day

    rows, _ = await fetch_cards(
        conn, CardQuery(lang="fr-FR", sort="air_date", sort2="popularity", descending2=False)
    )
    assert [row["id"] for row in rows if row["id"] in same_day] == list(reversed(same_day))


async def test_a_second_criterion_identical_to_the_first_is_ignored(
    conn: psycopg.AsyncConnection,
) -> None:
    """`order by x desc, x asc` est contradictoire et Postgres n'en dirait
    rien : on écarte le doublon plutôt que de produire la clause."""
    await seed(conn)
    q = CardQuery(lang="fr-FR", sort="air_date", sort2="air_date", descending2=False)

    assert q.criteria == (("air_date", True),)
    rows, _ = await fetch_cards(conn, q)
    assert [row["id"] for row in rows] == [1399, 2000]


async def test_only_with_a_poster(conn: psycopg.AsyncConnection) -> None:
    """La case « avec image ». TMDB n'a pas d'affiche pour tout le monde, et le
    fond de catalogue en est largement dépourvu."""
    await seed(conn)
    # Une série sans affiche, et une dont TMDB renvoie une chaîne vide plutôt
    # que `null` — les deux veulent dire la même chose.
    for tv_id, payload, digest in (
        (6001, '{"name": "Sans affiche", "first_air_date": "2019-01-01"}', b"\x41"),
        (
            6002,
            '{"name": "Affiche vide", "poster_path": "", "first_air_date": "2018-01-01"}',
            b"\x42",
        ),
    ):
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (%s, %s, 1.0, date '2026-08-05')",
            (tv_id, f"#{tv_id}"),
        )
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200, %s::jsonb, %s)
            """,
            (str(tv_id), payload, digest),
        )
    await refresh_cards(conn)

    tout, total_tout = await fetch_cards(conn, CardQuery(lang="fr-FR"))
    assert total_tout == 4
    assert {6001, 6002} <= {row["id"] for row in tout}

    avec, total_avec = await fetch_cards(conn, CardQuery(lang="fr-FR", with_poster=True))
    assert total_avec == 2, "le total suit le filtre, sinon la pagination ment"
    assert {row["id"] for row in avec} == {1399, 2000}
    assert all(row["posterPath"] for row in avec)


async def test_only_with_an_overview(conn: psycopg.AsyncConnection) -> None:
    """La case « avec descriptif ». C'est la matière de la notation : une série
    sans texte ne servira à rien, quelle que soit son affiche."""
    await seed(conn)
    for tv_id, payload, digest in (
        (7001, '{"name": "Sans texte", "poster_path": "/a.jpg"}', b"\x51"),
        # Le cas majoritaire en pratique : un synopsis non traduit revient en
        # chaîne vide, pas en `null`.
        (7002, '{"name": "Texte vide", "overview": "   ", "poster_path": "/b.jpg"}', b"\x52"),
    ):
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (%s, %s, 1.0, date '2026-08-05')",
            (tv_id, f"#{tv_id}"),
        )
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200, %s::jsonb, %s)
            """,
            (str(tv_id), payload, digest),
        )
    await refresh_cards(conn)

    _, total_tout = await fetch_cards(conn, CardQuery(lang="fr-FR"))
    assert total_tout == 4

    avec, total = await fetch_cards(conn, CardQuery(lang="fr-FR", with_overview=True))
    assert total == 2
    assert {row["id"] for row in avec} == {1399, 2000}

    # Les deux cases se combinent, elles ne s'excluent pas.
    _, deux = await fetch_cards(conn, CardQuery(lang="fr-FR", with_overview=True, with_poster=True))
    assert deux == 2


async def test_sorting_by_year_lets_the_second_criterion_work(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le tri par jour exact ne laisse presque jamais d'égalité à départager,
    donc le second critère paraît sans effet. À l'année, il en a un."""
    await seed(conn)
    for tv_id, date, pop, digest in (
        # Popularités choisies à contre-courant des dates : sans ça les deux
        # tris donneraient le même ordre et le test ne prouverait rien.
        (8001, "2020-01-05", 90.0, b"\x61"),
        (8002, "2020-11-30", 10.0, b"\x62"),
        (8003, "2020-06-15", 50.0, b"\x63"),
    ):
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (%s, %s, %s, date '2026-08-05')",
            (tv_id, f"#{tv_id}", pop),
        )
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200,
                    jsonb_build_object('name', %s::text, 'first_air_date', %s::text), %s)
            """,
            (str(tv_id), f"#{tv_id}", date, digest),
        )
    await refresh_cards(conn)
    lot = {8001, 8002, 8003}

    # Par jour : la date décide seule, la popularité n'a aucune égalité à
    # départager — c'est le comportement qui paraissait cassé.
    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="air_date", sort2="popularity"))
    assert [r["id"] for r in rows if r["id"] in lot] == [8002, 8003, 8001]

    # Par année : les trois sont à égalité, la popularité tranche — et donne un
    # ordre différent du précédent, ce qui est tout l'intérêt.
    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="air_year", sort2="popularity"))
    assert [r["id"] for r in rows if r["id"] in lot] == [8001, 8003, 8002]

    rows, _ = await fetch_cards(
        conn,
        CardQuery(lang="fr-FR", sort="air_year", sort2="popularity", descending2=False),
    )
    assert [r["id"] for r in rows if r["id"] in lot] == [8002, 8003, 8001]


async def test_the_rating_sort_weighs_the_number_of_voters(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le classement qu'on attend d'un tri « par note ».

    Sur `vote_average` brut, le sommet de la liste appartient aux séries qu'un
    seul votant a notées 10 — un classement que personne ne peut utiliser. La
    pondération bayésienne tire ces notes vers la moyenne du catalogue tant
    qu'elles ne reposent sur rien.
    """
    await seed(conn)
    for tv_id, note, votants, digest in (
        # 10/10, un seul votant : la note maximale, et aucune information.
        (9001, 10.0, 1, b"\x71"),
        # 8,8 sur cinq mille : moins bien noté, infiniment mieux établi.
        (9002, 8.8, 5000, b"\x72"),
        # 9,5 sur soixante : au-dessus du seuil, mais de peu.
        (9003, 9.5, 60, b"\x73"),
        # Aucun vote : ce n'est pas une note basse, c'est une absence de note.
        (9004, None, 0, b"\x74"),
    ):
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (%s, %s, 1.0, date '2026-08-05')",
            (tv_id, f"#{tv_id}"),
        )
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200,
                    jsonb_build_object('name', %s::text,
                                       'vote_average', %s::real,
                                       'vote_count', %s::int), %s)
            """,
            (str(tv_id), f"#{tv_id}", note, votants, digest),
        )
    await refresh_cards(conn)
    lot = {9001, 9002, 9003, 9004}

    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="rating"))
    classement = [row["id"] for row in rows if row["id"] in lot]

    # Les chiffres, pour que le classement attendu ne soit pas une incantation :
    #   9002 → (8,8 × 5000 + 6,5 × 50) / 5050 = 8,78  — le volume écrase le prior
    #   9003 → (9,5 ×   60 + 6,5 × 50) /  110 = 8,14  — soixante votes le tirent
    #                                                   encore vers la moyenne
    #   9001 → (10  ×    1 + 6,5 × 50) /   51 = 6,57  — un votant ne pèse rien
    # Une note plus haute peut donc passer derrière une note plus établie : c'est
    # le comportement recherché, pas un effet de bord.
    assert classement == [9002, 9003, 9001, 9004]

    # Dans l'autre sens, la série sans vote reste en fin de liste : elle n'est
    # ni la mieux ni la moins bien notée, elle n'est pas notée.
    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="rating", descending=False))
    assert [row["id"] for row in rows if row["id"] in lot][-1] == 9004


async def test_the_rating_sort_combines_with_popularity(conn: psycopg.AsyncConnection) -> None:
    """Le second critère, sur le tri qui vient d'arriver."""
    await seed(conn)
    for tv_id, pop, digest in ((9101, 5.0, b"\x81"), (9102, 90.0, b"\x82")):
        await conn.execute(
            "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
            " values (%s, %s, %s, date '2026-08-05')",
            (tv_id, f"#{tv_id}", pop),
        )
        await conn.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('tmdb', 'tv', %s, 'fr-FR', 200,
                    jsonb_build_object('name', %s::text,
                                       'vote_average', 7.5::real,
                                       'vote_count', 900::int), %s)
            """,
            (str(tv_id), f"#{tv_id}", digest),
        )
    await refresh_cards(conn)
    lot = {9101, 9102}

    # Note strictement identique : c'est la popularité qui doit trancher.
    rows, _ = await fetch_cards(conn, CardQuery(lang="fr-FR", sort="rating", sort2="popularity"))
    assert [row["id"] for row in rows if row["id"] in lot] == [9102, 9101]

    rows, _ = await fetch_cards(
        conn, CardQuery(lang="fr-FR", sort="rating", sort2="popularity", descending2=False)
    )
    assert [row["id"] for row in rows if row["id"] in lot] == [9101, 9102]


async def test_rich_sources_are_grouped_by_source(conn: psycopg.AsyncConnection) -> None:
    """L'enrichissement tel que la fiche le montre.

    Le groupement par source est celui de la lecture : Wikipédia porte une ligne
    par langue, Wikidata et TVmaze une seule chacune — leur contenu n'est pas
    linguistique. « Qu'apporte Wikipédia ? » est la question qu'on se pose, pas
    « qu'y a-t-il en français ? ».
    """
    await seed(conn)
    # L'enrichissement ne crée plus le pivot — la collecte l'a posé — il le
    # complète avec les identifiants trouvés dehors.
    await conn.execute(
        """
        update oeuvre set wikidata_qid = 'Q23572', imdb_id = 'tt0944947', tvmaze_id = 82,
                          titre = 'Game of Thrones', annee = 2011
        where univers = 'series' and id_tmdb = 1399
        """
    )
    oeuvre = await (
        await conn.execute("select id from oeuvre where univers = 'series' and id_tmdb = 1399")
    ).fetchone()
    assert oeuvre is not None

    long_article = "Le Trône de fer est une série télévisée. " * 100
    for source, lang, source_id, url, content, media, facts, voie in (
        (
            "wikipedia",
            "fr",
            "Le Trône de fer",
            "https://fr.wikipedia.org/wiki/Le_Trone_de_fer",
            long_article,
            [],
            {},
            "sitelink",
        ),
        ("wikipedia", "en", "Game of Thrones", None, "A television series.", [], {}, "sitelink"),
        (
            "wikidata",
            "",
            "Q23572",
            "https://www.wikidata.org/wiki/Q23572",
            None,
            [],
            {"pays": ["US"], "ids": {"wikidata": "Q23572", "imdb": "tt0944947"}},
            "qid",
        ),
        (
            "tvmaze",
            "",
            "82",
            "https://www.tvmaze.com/shows/82",
            "Résumé TVmaze.",
            [{"type": "poster", "url": "https://exemple.test/poster.jpg"}],
            {"statut": "terminee", "diffuseur": "HBO"},
            "imdb",
        ),
    ):
        await conn.execute(
            """
            insert into riche_source (oeuvre_id, id_tmdb, source, lang, source_id, url,
                                      content, media, facts, resolved_by)
            values (%s, 1399, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            """,
            (
                oeuvre[0],
                source,
                lang,
                source_id,
                url,
                content,
                json.dumps(media),
                json.dumps(facts),
                voie,
            ),
        )

    rich = await fetch_rich(conn, 1399)

    assert rich["oeuvre"]["wikidataQid"] == "Q23572"
    assert rich["oeuvre"]["tvmazeId"] == 82
    assert [groupe["source"] for groupe in rich["sources"]] == ["tvmaze", "wikidata", "wikipedia"]

    wikipedia = next(g for g in rich["sources"] if g["source"] == "wikipedia")
    assert [entree["lang"] for entree in wikipedia["entries"]] == ["en", "fr"]
    assert wikipedia["chars"] == len(long_article) + len("A television series.")

    # L'article long est tronqué, le court ne l'est pas — et le compte de
    # caractères dit la taille réelle dans les deux cas.
    longue = next(e for e in wikipedia["entries"] if e["lang"] == "fr")
    assert longue["truncated"] is True
    assert len(longue["extract"]) == EXTRAIT_CHARS
    assert longue["contentChars"] == len(long_article)

    courte = next(e for e in wikipedia["entries"] if e["lang"] == "en")
    assert courte["truncated"] is False
    assert courte["extract"] == "A television series."

    # Les faits canoniques traversent tels quels : c'est `normalize.py` qui
    # garantit leurs clés, l'admin n'a rien à réinterpréter.
    tvmaze = next(g for g in rich["sources"] if g["source"] == "tvmaze")
    assert tvmaze["entries"][0]["facts"]["diffuseur"] == "HBO"
    assert tvmaze["media"] == 1
    assert tvmaze["entries"][0]["media"][0]["type"] == "poster"


async def test_rich_sources_of_a_work_never_enriched(conn: psycopg.AsyncConnection) -> None:
    """Le cas le plus fréquent aujourd'hui : rien. Ce n'est pas une erreur —
    l'enrichissement passe après la collecte et ne couvre pas le catalogue.

    La série a bien un pivot — la collecte le pose depuis le lot 12 — mais il
    ne porte aucun identifiant externe, et c'est ça, « jamais enrichie ». Le
    panneau ne doit pas afficher un bloc d'identité vide sous prétexte que la
    ligne existe."""
    await seed(conn)

    assert (
        await (
            await conn.execute("select id from oeuvre where univers = 'series' and id_tmdb = 1399")
        ).fetchone()
        is not None
    ), "le pivot existe : la fiche a été collectée"

    rich = await fetch_rich(conn, 1399)

    assert rich["oeuvre"] is None, "aucun identifiant externe : rien à montrer"
    assert rich["sources"] == []


async def test_a_collection_that_stored_nothing_never_lights_the_banner(
    conn: psycopg.AsyncConnection,
) -> None:
    """Observé en production : `fetch_state` disait « succès 200 » pour 226
    séries sans aucune ligne dans `raw_source`. Le bandeau se mesurait contre
    cette table et restait allumé pour toujours — aucun rafraîchissement ne peut
    projeter une série dont le brut n'existe pas."""
    await seed(conn)
    await conn.execute(
        """
        insert into fetch_state (source, kind, source_id, last_fetched_at,
                                 last_success_at, last_status)
        values ('tmdb', 'tv', '999001', now(), now(), 200),
               ('tmdb', 'tv', '999002', now(), now(), 200)
        """
    )
    await refresh_cards(conn)

    etat = await cards_state(conn)

    assert etat["collected"] == 4, "fetch_state en compte quatre…"
    assert etat["projectable"] == 2, "… mais deux seulement ont un brut exploitable"
    assert etat["projected"] == 2
    assert etat["pending"] == 0
    assert etat["stale"] is False, "rien à rafraîchir : le bandeau doit rester éteint"


async def test_projection_state_says_when_it_lags(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    assert await cards_state(conn) == {
        "projected": 2,
        "collected": 2,
        "projectable": 2,
        "pending": 0,
        "stale": False,
        "lastAt": (await cards_state(conn))["lastAt"],
    }

    # Une série collectée après le dernier rafraîchissement : la projection est
    # en retard, et doit le dire plutôt que de faire disparaître la série.
    await conn.execute(
        """
        insert into raw_source (source, kind, source_id, lang, http_status, payload, payload_sha256)
        values ('tmdb', 'tv', '4000', 'fr-FR', 200, '{"name": "Neuve"}'::jsonb, '\\x21'::bytea)
        """
    )
    await conn.execute(
        """
        insert into fetch_state (source, kind, source_id, last_fetched_at, last_success_at,
                                 last_status)
        values ('tmdb', 'tv', '4000', now(), now(), 200)
        """
    )
    assert (await cards_state(conn))["stale"] is True

    assert await refresh_cards(conn) == 3
    assert (await cards_state(conn))["stale"] is False


async def test_work_detail_flattens_the_payload(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    work = await fetch_work(conn, 1399, "fr-FR")

    assert work is not None
    assert work["name"] == "Le Trône de fer"
    assert work["tagline"] == "L'hiver vient"
    assert work["genres"] == ["Drame", "Fantastique"]
    assert work["networks"] == [{"name": "HBO", "logoPath": "/hbo.png"}]
    assert work["createdBy"] == ["David Benioff"]
    assert work["externalIds"]["wikidata_id"] == "Q23572"
    assert work["catalog"]["popularity"] == 400.0
    assert work["axisScores"] is None, "jamais notée : pas de vecteur, pas de zéros"
    assert work["videos"] == [], "canal vidéo jamais passé : liste vide, pas d'absence"


async def test_work_detail_orders_the_videos(conn: psycopg.AsyncConnection) -> None:
    """La meilleure d'abord : `priorite` tranche le type et l'officialité, la
    langue départage ensuite — français, puis anglais, puis le reste."""
    await seed(conn)
    await conn.execute(
        f"""
        insert into sourcing.video (oeuvre_id, site, cle, type, nom, lang, officiel, saison)
        values
            ({pivot(1399)}, 'YouTube', 'clip', 'Clip',    'Extrait',   'en', true,  null),
            ({pivot(1399)}, 'YouTube', 'vo',   'Trailer', 'Trailer',   'en', true,  null),
            ({pivot(1399)}, 'YouTube', 'vf',   'Trailer', 'Annonce',   'fr', true,  null),
            ({pivot(1399)}, 'YouTube', 'fan',  'Trailer', 'Officieux', 'fr', false, null),
            ({pivot(1399)}, 'YouTube', 's2',   'Teaser',  'Saison 2',  'en', true,  2)
        """
    )

    work = await fetch_work(conn, 1399, "fr-FR")

    assert work is not None
    assert [v["key"] for v in work["videos"]] == ["vf", "vo", "fan", "s2", "clip"], (
        "bande-annonce officielle française, puis anglaise, puis l'officieuse, "
        "puis le teaser, l'extrait en dernier"
    )
    premiere = work["videos"][0]
    assert premiere["site"] == "YouTube"
    assert premiere["official"] is True
    assert premiere["season"] is None
    assert work["videos"][3]["season"] == 2


async def test_work_detail_hides_dead_videos(conn: psycopg.AsyncConnection) -> None:
    """Une bande-annonce retirée de YouTube reste en base — la re-projection
    depuis le brut la recréerait — mais la fiche cesse d'en proposer le
    lecteur. Une vidéo jamais vérifiée reste montrée : la prudence ne doit pas
    vider l'onglet avant la première passe de contrôle."""
    await seed(conn)
    await conn.execute(
        f"""
        insert into sourcing.video (oeuvre_id, site, cle, type, nom, lang, officiel, vivante)
        values
            ({pivot(1399)}, 'YouTube', 'morte',    'Trailer', 'Retiree',  'fr', true, false),
            ({pivot(1399)}, 'YouTube', 'vivante',  'Trailer', 'Lisible',  'fr', true, true),
            ({pivot(1399)}, 'YouTube', 'inconnue', 'Trailer', 'Pas vue',  'fr', true, null)
        """
    )

    work = await fetch_work(conn, 1399, "fr-FR")

    assert work is not None
    assert sorted(v["key"] for v in work["videos"]) == ["inconnue", "vivante"]


async def test_work_detail_carries_the_axis_vector(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    await conn.execute(
        f"""
        insert into notation.score
            (oeuvre_id, axe, valeur, confiance, rubric_version, modele,
             input_sha256, prompt_sha256, scored_at)
        values ({pivot(1399)}, 'sensoriel', 7, 0.9, 'v1', 'gpt-test',
                'sha-in', 'sha-p', now())
        """
    )

    work = await fetch_work(conn, 1399, "fr-FR")

    assert work is not None
    assert work["axisScores"] == {"sensoriel": 7.0}


async def test_the_fiche_is_shown_in_the_chosen_language(
    conn: psycopg.AsyncConnection,
) -> None:
    """La fiche n'est téléchargée qu'en `fr-FR`, mais ses traductions voyagent
    dans le même payload. Sans les lire, changer de langue ne changeait rien au
    texte affiché."""
    await seed(conn)

    arabe = await fetch_work(conn, 1399, "ar-SA")
    assert arabe is not None
    assert arabe["name"] == "لعبة العروش"
    assert arabe["overview"].startswith("تسع عائلات")
    assert arabe["tagline"] == "الشتاء قادم"
    assert arabe["translated"] == {"lang": "ar-SA", "name": True, "overview": True}

    francais = await fetch_work(conn, 1399, "fr-FR")
    assert francais is not None
    assert francais["name"] == "Le Trône de fer"


async def test_a_missing_translation_falls_back_and_says_so(
    conn: psycopg.AsyncConnection,
) -> None:
    """Afficher un synopsis français en prétendant montrer le turc induirait en
    erreur sur ce qui est réellement collecté — ce que ce tableau de bord a
    précisément pour rôle de mesurer."""
    await seed(conn)
    turc = await fetch_work(conn, 1399, "tr-TR")

    assert turc is not None
    assert turc["name"] == "Taht Oyunları"  # traduit
    assert turc["overview"].startswith("Neuf familles")  # replié sur le français
    assert turc["translated"] == {"lang": "tr-TR", "name": True, "overview": False}

    # Une langue absente des traductions : le titre retombe sur l'original — ce
    # que fait TMDB — et le synopsis sur le français, faute de mieux.
    espagnol = await fetch_work(conn, 1399, "es-ES")
    assert espagnol is not None
    assert espagnol["name"] == "Game of Thrones"
    assert espagnol["translated"] == {"lang": "es-ES", "name": False, "overview": False}


async def test_an_empty_field_falls_through_to_another_region(
    conn: psycopg.AsyncConnection,
) -> None:
    """Observé sur la fiche réelle de *Game of Thrones* : `de-DE` a un `name`
    vide et un `overview` rempli. Prendre l'entrée telle quelle afficherait un
    titre blanc ; il faut le premier champ **non vide**, champ par champ."""
    await seed(conn)
    allemand = await fetch_work(conn, 1399, "de-DE")

    assert allemand is not None
    assert allemand["overview"] == "Die Handlung…", "le synopsis allemand existe"
    assert allemand["name"] == "Game of Thrones", "le titre non traduit retombe sur l'original"
    assert allemand["translated"] == {"lang": "de-DE", "name": False, "overview": True}


async def test_the_regional_variant_decides(conn: psycopg.AsyncConnection) -> None:
    """TMDB renvoie plusieurs variantes d'une même langue (ar-AE, ar-SA). Prendre
    la première venue donnerait un résultat instable d'une collecte à l'autre."""
    await seed(conn)
    saoudien = await fetch_work(conn, 1399, "ar-SA")

    assert saoudien is not None
    assert saoudien["name"] == "لعبة العروش", "la variante SA doit primer sur AE"


async def test_gallery_and_cast_are_truncated_in_sql(conn: psycopg.AsyncConnection) -> None:
    """Une fiche TMDB porte des centaines de visuels ; les transporter tous
    rendrait la modale plus lourde que toute la grille."""
    await seed(conn)
    work = await fetch_work(conn, 1399, "fr-FR")

    assert work is not None
    assert len(work["gallery"]["backdrops"]) == 18
    assert work["gallery"]["backdrops"][0] == "/backdrop-0.jpg"
    assert len(work["gallery"]["posters"]) == 4  # moins que la limite : tout passe
    assert len(work["cast"]) == 30
    assert work["cast"][0] == {
        "id": 100,
        "name": "Comédien 0",
        "character": "Personnage 0",
        "profilePath": "/face-0.jpg",
        "episodeCount": 60,
    }


async def test_seasons_report_their_languages(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    work = await fetch_work(conn, 1399, "ar-SA")

    assert work is not None
    first, second = work["seasons"]
    assert first["seasonNumber"] == 1
    assert first["episodeCount"] == 10
    assert set(first["collected"]) == {"fr-FR", "ar-SA"}
    assert first["hasSelectedLang"] is True

    # La saison 2 a été tentée en arabe et a échoué : elle est « connue » dans
    # cette langue, mais son 404 se voit.
    assert second["collected"]["ar-SA"]["status"] == 404


async def test_watch_providers_follow_the_country_of_the_language(
    conn: psycopg.AsyncConnection,
) -> None:
    """TMDB indexe la disponibilité par pays. Le sélecteur de langue porte déjà
    la région : `fr-FR` interroge la France, `ar-SA` l'Arabie saoudite."""
    await seed(conn)

    france = await fetch_work(conn, 1399, "fr-FR")
    arabie = await fetch_work(conn, 1399, "ar-SA")

    assert france is not None and arabie is not None
    assert france["watch"]["country"] == "FR"
    assert [offer["kind"] for offer in france["watch"]["offers"]] == ["flatrate", "rent"]
    # Trié par `display_priority` : Netflix (1) avant Prime Video (3).
    assert [p["name"] for p in france["watch"]["offers"][0]["providers"]] == [
        "Netflix",
        "Prime Video",
    ]
    assert france["watch"]["link"].endswith("locale=FR")

    assert arabie["watch"]["country"] == "SA"
    assert [p["name"] for p in arabie["watch"]["offers"][0]["providers"]] == ["Shahid VIP"]


async def test_a_country_without_offer_is_not_a_missing_datum(
    conn: psycopg.AsyncConnection,
) -> None:
    """« Pas de plateforme en Turquie » et « aucune donnée de disponibilité »
    sont deux choses différentes, et le front doit pouvoir les distinguer."""
    await seed(conn)
    turquie = await fetch_work(conn, 1399, "tr-TR")

    assert turquie is not None
    assert turquie["watch"]["offers"] == []
    # … mais on sait que la série est disponible ailleurs.
    assert turquie["watch"]["countries"] == ["FR", "SA"]

    # Une série dont le brut ne porte aucun `watch/providers` : rien du tout.
    sans = await fetch_work(conn, 2000, "fr-FR")
    assert sans is not None
    assert sans["watch"]["offers"] == [] and sans["watch"]["countries"] == []


async def test_work_absent_from_the_raw(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    assert await fetch_work(conn, 4000, "fr-FR") is None


async def test_season_episodes_follow_the_selected_language(
    conn: psycopg.AsyncConnection,
) -> None:
    """C'est le cœur du sélecteur de langue : les synopsis d'épisode changent
    parce que la collecte a redemandé la saison entière dans cette langue."""
    await seed(conn)

    french = await fetch_season(conn, 1399, 1, "fr-FR")
    arabic = await fetch_season(conn, 1399, 1, "ar-SA")

    assert french is not None and arabic is not None
    assert french["episodes"][0]["overview"].startswith("Synopsis français")
    assert arabic["episodes"][0]["overview"].startswith("ملخص")
    assert french["name"] == "Saison 1" and arabic["name"] == "الموسم 1"
    assert [episode["episodeNumber"] for episode in french["episodes"]] == [1, 2]

    # Une saison en échec dans une langue n'a rien à montrer, et le dit.
    assert await fetch_season(conn, 1399, 2, "ar-SA") is None
    assert await fetch_season(conn, 1399, 9, "fr-FR") is None
