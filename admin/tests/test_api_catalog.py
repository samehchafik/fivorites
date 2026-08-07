"""Les routes de navigation, vues du navigateur."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
import pytest_asyncio

from conftest import requires_db
from fiv_admin.app import create_app
from fiv_admin.config import Settings
from fiv_admin.security import hash_password
from test_catalog import seed

pytestmark = [pytest.mark.integration, requires_db]

PASSWORD = "un mot de passe assez long"


@pytest_asyncio.fixture
async def client(
    conn: psycopg.AsyncConnection, settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    await conn.execute(
        "insert into admin_user (username, password_hash) values (%s, %s)",
        ("sameh", hash_password(PASSWORD)),
    )
    await seed(conn)

    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        await http.post("/api/auth/login", json={"username": "sameh", "password": PASSWORD})
        yield http


async def test_cards_route(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/catalog/cards", params={"lang": "ar-SA"})).json()

    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [1399, 2000]
    assert body["projection"] == {
        "projected": 2,
        "collected": 2,
        "projectable": 2,
        "pending": 0,
        "stale": False,
        "lastAt": body["projection"]["lastAt"],
    }
    assert body["items"][0]["selected"] == {"lang": "ar-SA", "ok": 1, "failed": 1, "ratio": 0.5}


async def test_cards_need_a_session() -> None:
    """Sans fixture connectée : la grille est derrière la session comme le reste."""
    from fiv_admin.app import create_app as build
    from fiv_admin.config import Settings as Config

    app = build(Config(admin_secret_key="x", cors_origins="", web_dist="/inexistant"))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        assert (await http.get("/api/catalog/cards")).status_code == 401


async def test_the_filters_change_the_total(client: httpx.AsyncClient) -> None:
    """Le total doit suivre les cases cochées : un compteur qui reste au total
    général annonce des pages qui n'existent pas, et laisse croire que le filtre
    n'a rien fait."""
    tout = (await client.get("/api/catalog/cards", params={"lang": "fr-FR"})).json()
    assert tout["total"] == 2

    # Les deux séries semées ont affiche et synopsis : on en ajoute une nue.
    sans = (
        await client.get("/api/catalog/cards", params={"lang": "fr-FR", "search": "باب"})
    ).json()
    assert sans["total"] == 1, "la recherche aussi doit compter juste"

    # Le total non filtré reste disponible pour l'affichage « x / y ».
    assert tout["projection"]["projected"] == 2


async def test_work_route(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/catalog/works/1399", params={"lang": "fr-FR"})).json()

    assert body["name"] == "Le Trône de fer"
    assert len(body["cast"]) == 30
    assert len(body["gallery"]["backdrops"]) == 18
    assert [season["seasonNumber"] for season in body["seasons"]] == [1, 2]

    missing = await client.get("/api/catalog/works/4000")
    assert missing.status_code == 404
    assert "encore été téléchargée" in missing.json()["detail"]


async def test_season_route_follows_the_language(client: httpx.AsyncClient) -> None:
    french = (
        await client.get("/api/catalog/works/1399/seasons/1", params={"lang": "fr-FR"})
    ).json()
    arabic = (
        await client.get("/api/catalog/works/1399/seasons/1", params={"lang": "ar-SA"})
    ).json()

    assert french["episodes"][0]["overview"] != arabic["episodes"][0]["overview"]

    absent = await client.get("/api/catalog/works/1399/seasons/2", params={"lang": "ar-SA"})
    assert absent.status_code == 404


async def test_refresh_route(client: httpx.AsyncClient, conn: psycopg.AsyncConnection) -> None:
    await conn.execute(
        """
        insert into raw_source (source, kind, source_id, lang, http_status, payload, payload_sha256)
        values ('tmdb', 'tv', '4000', 'fr-FR', 200, '{"name": "Neuve"}'::jsonb, '\\x31'::bytea)
        """
    )
    body = (await client.post("/api/catalog/refresh")).json()
    assert body["projected"] == 3
    assert body["stale"] is False
