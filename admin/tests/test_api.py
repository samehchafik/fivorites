"""L'API vue du navigateur : session, refus, et forme des réponses."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb

from conftest import requires_db
from fiv_admin.app import create_app
from fiv_admin.config import Settings
from fiv_admin.security import hash_password
from test_queries import seed

pytestmark = [pytest.mark.integration, requires_db]

PASSWORD = "un mot de passe assez long"


@pytest_asyncio.fixture
async def client(
    conn: psycopg.AsyncConnection, settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    await conn.execute(
        "insert into admin_user (username, password_hash, display_name) values (%s, %s, %s)",
        ("sameh", hash_password(PASSWORD), "Sameh"),
    )
    await seed(conn)

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def login(client: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/auth/login", json={"username": "sameh", "password": password})


async def test_login_sets_an_httponly_session(client: httpx.AsyncClient) -> None:
    response = await login(client)

    assert response.status_code == 200
    assert response.json() == {"username": "sameh", "displayName": "Sameh"}

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie, "un jeton lisible en JavaScript est exfiltrable"
    assert "SameSite=strict" in cookie.replace("samesite", "SameSite")

    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "sameh"


async def test_wrong_password_is_refused(client: httpx.AsyncClient) -> None:
    response = await login(client, "mot de passe faux mais long")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_unknown_account_answers_like_a_wrong_password(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login", json={"username": "personne", "password": "quelque chose"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "identifiants invalides"


async def test_throttle_locks_the_account_after_repeated_failures(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(5):
        assert (await login(client, "faux")).status_code == 401

    blocked = await login(client, "faux")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # Le bon mot de passe ne contourne pas le verrou : sinon il n'en serait pas un.
    assert (await login(client)).status_code == 429


async def test_everything_else_needs_a_session(client: httpx.AsyncClient) -> None:
    for path in ("/api/meta", "/api/acquisition/summary", "/api/acquisition/items"):
        assert (await client.get(path)).status_code == 401


async def test_logout_clears_the_session(client: httpx.AsyncClient) -> None:
    await login(client)
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_disabling_an_account_takes_effect_immediately(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    """Le jeton reste valide douze heures : c'est le compte qu'on revérifie à
    chaque requête, pas seulement la signature."""
    await login(client)
    await conn.execute("update admin_user set disabled = true where username = 'sameh'")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_forged_cookie_is_refused(client: httpx.AsyncClient) -> None:
    client.cookies.set("fiv_admin_session", "nimportequoi.signaturebidon")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_items_shape(client: httpx.AsyncClient) -> None:
    await login(client)
    response = await client.get("/api/acquisition/items", params={"lang": "ar-SA", "pageSize": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["lang"] == "ar-SA"
    assert body["languages"][0] == "fr-FR"

    got = next(item for item in body["items"] if item["id"] == 1399)
    assert got["state"] == "partial"
    assert got["selected"] == {
        "lang": "ar-SA",
        "ok": 1,
        "failed": 0,
        "lastAt": got["selected"]["lastAt"],
        "ratio": 0.5,
    }


async def test_meta_merges_configured_and_observed_languages(client: httpx.AsyncClient) -> None:
    await login(client)
    body = (await client.get("/api/meta")).json()

    codes = [language["code"] for language in body["languages"]]
    assert codes[:5] == ["fr-FR", "en-US", "es-ES", "ar-SA", "tr-TR"]
    assert {language["code"]: language["label"] for language in body["languages"]}[
        "ar-SA"
    ] == "Arabe"
    assert [media["key"] for media in body["media"]] == ["tv", "movie"]
    assert [media["available"] for media in body["media"]] == [True, True], (
        "les deux univers sont servis depuis le lot 13"
    )


async def test_les_deux_univers_sont_servis_et_ne_se_melangent_pas(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    """Un film collecté apparaît côté films, et **jamais** côté séries.

    Le second point n'est pas de la coquetterie : les identifiants TMDB des
    deux univers se chevauchent, et une grille qui mélangerait les deux
    afficherait *Fight Club* dans la liste des séries.
    """
    await login(client)
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'movie', '550', 'fr-FR', 200, %s, %s)",
        (Jsonb({"title": "Fight Club", "release_date": "1999-10-15"}), b"\x99"),
    )
    await conn.execute("refresh materialized view admin.movie_card")

    films = (await client.get("/api/catalog/cards", params={"media": "movie"})).json()
    assert [item["id"] for item in films["items"]] == [550]
    assert films["items"][0]["name"] == "Fight Club", "`title` se lit sous le nom `name`"

    series = (await client.get("/api/catalog/cards", params={"media": "tv"})).json()
    assert 550 not in [item["id"] for item in series["items"]]


async def test_un_univers_inconnu_est_refuse(client: httpx.AsyncClient) -> None:
    """La clé sert à choisir un nom de vue : une valeur libre y serait une
    injection, et la liste fermée est ce qui l'empêche."""
    await login(client)
    reponse = await client.get("/api/catalog/cards", params={"media": "livres"})
    assert reponse.status_code == 422
    assert "univers inconnu" in reponse.json()["detail"]


async def test_unknown_sort_is_refused_rather_than_ignored(client: httpx.AsyncClient) -> None:
    await login(client)
    response = await client.get("/api/acquisition/items", params={"sort": "popularity; drop"})
    assert response.status_code == 422


async def test_detail(client: httpx.AsyncClient) -> None:
    await login(client)
    body = (await client.get("/api/acquisition/items/1399")).json()
    assert body["payload"]["name"] == "Le Trône de fer"
    assert (await client.get("/api/acquisition/items/123456")).status_code == 404


async def test_health_needs_no_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/health")).json() == {"status": "ok"}
