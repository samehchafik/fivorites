"""Le tableau d'acquisition, sur des données semées.

Ces tests portent sur la seule chose que le front ne peut pas vérifier
lui-même : que l'état affiché pour une œuvre **dans une langue donnée** dise la
vérité sur ce qui est en base.
"""

from __future__ import annotations

import psycopg
import pytest

from conftest import requires_db
from fiv_admin.media import MEDIA
from fiv_admin.queries import (
    ItemsQuery,
    fetch_detail,
    fetch_items,
    fetch_summary,
    observed_languages,
)

pytestmark = [pytest.mark.integration, requires_db]

TV = MEDIA["tv"]


async def seed(conn: psycopg.AsyncConnection) -> None:
    """Quatre séries qui couvrent les quatre états qu'on veut distinguer.

    1399 — collectée, complète en français, à moitié en arabe, en échec en anglais
    2000 — collectée, mais aucune saison énumérée (fiche seule)
    3000 — regardée, jamais aboutie (jeton refusé)
    4000 — jamais regardée
    """
    await conn.execute(
        """
        insert into tmdb_catalog (id, original_name, popularity, exported_on) values
            (1399, 'Game of Thrones', 400.0, date '2026-08-05'),
            (2000, 'باب الحارة',       11.4, date '2026-08-05'),
            (3000, 'Muhteşem Yüzyıl',  20.8, date '2026-08-05'),
            (4000, 'Série obscure',     0.1, date '2026-08-05')
        """
    )

    # Les fiches.
    await conn.execute(
        """
        insert into fetch_state (source, kind, source_id, last_fetched_at,
                                 last_success_at, last_status, last_error) values
            ('tmdb', 'tv', '1399', now(), now(), 200, null),
            ('tmdb', 'tv', '2000', now(), now(), 200, null),
            ('tmdb', 'tv', '3000', now(), null,  401, 'HTTP 401')
        """
    )
    await conn.execute(
        """
        insert into raw_source (source, kind, source_id, lang, http_status, payload, payload_sha256)
        values ('tmdb', 'tv', '1399', 'fr-FR', 200,
                '{"name": "Le Trône de fer",
                  "seasons": [{"season_number": 1}, {"season_number": 2}],
                  "translations": {"translations": [{"iso_639_1": "fr"},
                                                    {"iso_639_1": "ar"}]}}'::jsonb,
                '\\x01'::bytea)
        """
    )

    # Les deux saisons de 1399 ont été énumérées : c'est le dénominateur.
    await conn.execute(
        """
        insert into fetch_state (source, kind, source_id, last_fetched_at,
                                 last_success_at, last_status) values
            ('tmdb', 'tv_season', '1399/s1', now(), now(), 200),
            ('tmdb', 'tv_season', '1399/s2', now(), now(), 200)
        """
    )

    # Le brut, langue par langue : français complet, arabe partiel, anglais en échec.
    await conn.execute(
        """
        insert into raw_source (source, kind, source_id, lang, http_status, payload, payload_sha256)
        values
            ('tmdb', 'tv_season', '1399/s1', 'fr-FR', 200, '{}'::jsonb, '\\x02'::bytea),
            ('tmdb', 'tv_season', '1399/s2', 'fr-FR', 200, '{}'::jsonb, '\\x03'::bytea),
            ('tmdb', 'tv_season', '1399/s1', 'ar-SA', 200, '{}'::jsonb, '\\x04'::bytea),
            ('tmdb', 'tv_season', '1399/s1', 'en-US', 404, null,        '\\x05'::bytea)
        """
    )


async def test_states_depend_on_the_selected_language(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)

    def state_of(rows: list[dict], work_id: int) -> str:
        return next(row["state"] for row in rows if row["id"] == work_id)

    fr, total = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR"))
    assert total == 4
    assert state_of(fr, 1399) == "complete"  # 2 saisons attendues, 2 collectées
    assert state_of(fr, 2000) == "series_only"  # fiche récupérée, aucune saison énumérée
    assert state_of(fr, 3000) == "error"  # regardée, jamais aboutie
    assert state_of(fr, 4000) == "absent"  # jamais regardée

    ar, _ = await fetch_items(conn, ItemsQuery(media=TV, lang="ar-SA"))
    assert state_of(ar, 1399) == "partial"  # 1 saison sur 2

    en, _ = await fetch_items(conn, ItemsQuery(media=TV, lang="en-US"))
    assert state_of(en, 1399) == "lang_missing"  # une saison tentée, aucune obtenue


async def test_coverage_carries_every_language_not_only_the_selected_one(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le tableau montre une pastille par langue sur chaque ligne : une seule
    requête doit donc ramener toutes les langues, pas seulement la choisie."""
    await seed(conn)
    rows, _ = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR"))
    got = next(row for row in rows if row["id"] == 1399)

    assert got["expectedParts"] == 2
    assert got["coverage"]["fr-FR"]["ok"] == 2
    assert got["coverage"]["ar-SA"]["ok"] == 1
    assert got["coverage"]["en-US"] == {
        "ok": 0,
        "failed": 1,
        "lastAt": got["coverage"]["en-US"]["lastAt"],
    }
    assert got["selected"]["ratio"] == 1.0


async def test_status_filters(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)

    async def ids(status: str, lang: str = "fr-FR") -> set[int]:
        rows, _ = await fetch_items(conn, ItemsQuery(media=TV, lang=lang, status=status))
        return {row["id"] for row in rows}

    assert await ids("absent") == {4000}
    assert await ids("collected") == {1399, 2000}
    assert await ids("error") == {3000}
    assert await ids("lang_ok") == {1399}
    assert await ids("lang_ok", lang="en-US") == set()  # le 404 ne compte pas
    assert await ids("lang_missing", lang="en-US") == {1399, 2000}


async def test_search_matches_title_or_id(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)

    rows, total = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR", search="thrones"))
    assert total == 1 and rows[0]["id"] == 1399

    rows, total = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR", search="3000"))
    assert total == 1 and rows[0]["id"] == 3000

    # L'arabe passe par le même chemin que le reste — pas de repli ASCII.
    rows, total = await fetch_items(conn, ItemsQuery(media=TV, lang="ar-SA", search="الحارة"))
    assert total == 1 and rows[0]["id"] == 2000


async def test_sorting(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)

    rows, _ = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR", sort="popularity"))
    assert [row["id"] for row in rows] == [1399, 3000, 2000, 4000]

    rows, _ = await fetch_items(
        conn, ItemsQuery(media=TV, lang="fr-FR", sort="id", descending=False)
    )
    assert [row["id"] for row in rows] == [1399, 2000, 3000, 4000]

    # Le tri par fraîcheur ne liste que ce qui a été regardé : 4000 disparaît,
    # et c'est le comportement attendu, pas un oubli.
    rows, total = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR", sort="fetched"))
    assert {row["id"] for row in rows} == {1399, 2000, 3000}
    assert total == 3


async def test_pagination_reports_the_full_total(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    rows, total = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR", page_size=2))
    assert len(rows) == 2 and total == 4

    second, _ = await fetch_items(conn, ItemsQuery(media=TV, lang="fr-FR", page_size=2, page=2))
    assert {row["id"] for row in rows} & {row["id"] for row in second} == set()


async def test_summary_counts_by_language(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    summary = await fetch_summary(conn, TV)

    assert summary["catalog"]["total"] == 4
    assert summary["works"] == {
        "seen": 3,
        "ok": 2,
        "failed": 1,
        # 4 séries au catalogue, 3 regardées : il en reste une.
        "remaining": 1,
        "lastHour": 3,
        "lastAt": summary["works"]["lastAt"],
    }
    assert summary["parts"]["expected"] == 2
    assert summary["byLang"]["fr-FR"]["partsOk"] == 2
    assert summary["byLang"]["ar-SA"]["partsOk"] == 1
    assert summary["byLang"]["en-US"] == {
        "rows": 1,
        "partsOk": 0,
        "worksOk": 0,
        "failed": 1,
        "lastAt": summary["byLang"]["en-US"]["lastAt"],
    }
    assert [error["sourceId"] for error in summary["errors"]] == ["3000"]


async def test_remaining_never_goes_negative(conn: psycopg.AsyncConnection) -> None:
    """Une série peut être collectée puis disparaître de l'export TMDB — le
    catalogue rétrécit, `fetch_state` non. Un « reste −3 » à l'écran ferait
    douter de tout le reste du tableau."""
    await seed(conn)
    await conn.execute("delete from tmdb_catalog where id in (3000, 4000)")

    summary = await fetch_summary(conn, TV)

    assert summary["catalog"]["total"] == 2
    assert summary["works"]["seen"] == 3
    assert summary["works"]["remaining"] == 0


async def test_observed_languages(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    assert await observed_languages(conn, TV) == ["ar-SA", "en-US", "fr-FR"]


async def test_detail_opens_the_payload(conn: psycopg.AsyncConnection) -> None:
    await seed(conn)
    detail = await fetch_detail(conn, TV, 1399)

    assert detail is not None
    assert detail["payload"]["name"] == "Le Trône de fer"
    assert detail["payload"]["seasonsDeclared"] == 2
    assert sorted(detail["payload"]["translations"]) == ["ar", "fr"]
    assert [part["id"] for part in detail["parts"]] == ["1399/s1", "1399/s2"]
    assert detail["parts"][0]["langs"]["en-US"]["status"] == 404
    assert set(detail["parts"][1]["langs"]) == {"fr-FR"}

    assert await fetch_detail(conn, TV, 123456) is None


async def test_detail_sorts_seasons_by_number_not_by_text(conn: psycopg.AsyncConnection) -> None:
    """`1399/s10` après `1399/s2` — un tri texte les met à l'envers, et un
    tableau de saisons dans le désordre est illisible."""
    await seed(conn)
    await conn.execute(
        """
        insert into raw_source (source, kind, source_id, lang, http_status, payload, payload_sha256)
        values ('tmdb', 'tv_season', '1399/s10', 'fr-FR', 200, '{}'::jsonb, '\\x06'::bytea)
        """
    )
    detail = await fetch_detail(conn, TV, 1399)
    assert detail is not None
    assert [part["id"] for part in detail["parts"]] == ["1399/s1", "1399/s2", "1399/s10"]
