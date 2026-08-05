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
    CardQuery,
    cards_state,
    fetch_cards,
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
    "translations": {"translations": [{"iso_639_1": "fr"}, {"iso_639_1": "ar"}]},
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


async def seed(conn: psycopg.AsyncConnection) -> None:
    await conn.execute(
        """
        insert into tmdb_catalog (id, original_name, popularity, exported_on) values
            (1399, 'Game of Thrones', 400.0, date '2026-08-05'),
            (2000, 'باب الحارة',       11.4, date '2026-08-05'),
            (4000, 'Jamais collectée',  0.1, date '2026-08-05')
        """
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


async def test_projection_state_says_when_it_lags(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    assert await cards_state(conn) == {
        "projected": 2,
        "collected": 2,
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
