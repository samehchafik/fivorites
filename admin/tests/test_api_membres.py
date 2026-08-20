"""Les membres et leurs tops, vus du navigateur."""

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


async def semer_membres(conn: psycopg.AsyncConnection) -> None:
    """Trois membres, et chacun porte un cas que la route doit savoir rendre.

    Alice a un compte et un top complet ; Bob est un invité — pas d'email, un
    top quand même ; Carla n'a rien publié. C'est exactement la population de
    l'import : 32 349 comptes, 37 006 invités, et des membres sans top.
    """
    await seed(conn)  # 1399 et 2000 collectées, leur pivot existe
    await conn.execute(
        """
        insert into membre.membre (id, v1_id, pseudo, creation) overriding system value values
            (1, 101, 'alice', now()),
            (2, 102, 'bob',   now()),
            (3, 103, 'carla', now())
        """
    )
    await conn.execute(
        "insert into membre.identifiant (membre_id, email) values (1, 'alice@exemple.fr')"
    )
    await conn.execute(
        """
        insert into membre.five (id, v1_id, membre_id, univers, periode) overriding system value
        values (10, 201, 1, 'series', 'life'),
               (11, 202, 2, 'series', 'life')
        """
    )
    oeuvres = await conn.execute(
        "select id_tmdb, id from oeuvre where univers = 'series' order by id_tmdb"
    )
    pivots = {tmdb: pivot for tmdb, pivot in await oeuvres.fetchall()}
    await conn.execute(
        """
        insert into membre.five_position (five_id, rang, oeuvre_id, titre_saisi, pourquoi)
        values (10, 1, %s, 'Game of Thrones', 'pour la fin, évidemment'),
               (10, 2, %s, 'Bab Al-Hara', null),
               (11, 1, %s, 'Game of Thrones', null)
        """,
        (pivots[1399], pivots[2000], pivots[1399]),
    )


@pytest_asyncio.fixture
async def client(
    conn: psycopg.AsyncConnection, settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    await conn.execute(
        "insert into admin_user (username, password_hash) values (%s, %s)",
        ("sameh", hash_password(PASSWORD)),
    )
    await semer_membres(conn)

    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        await http.post("/api/auth/login", json={"username": "sameh", "password": PASSWORD})
        yield http


async def test_liste_compte_les_tops(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/membres", params={"tri": "fives"})).json()

    assert body["total"] == 3
    par_pseudo = {m["pseudo"]: m for m in body["items"]}
    assert par_pseudo["alice"] == {
        "id": 1,
        "pseudo": "alice",
        "email": "alice@exemple.fr",
        "fives": 1,
        "positions": 2,
        "bani": False,
        "valide": True,
        "masque": True,
        "creation": par_pseudo["alice"]["creation"],
        "derniereConnexion": None,
    }
    # L'invité n'a pas d'email et ce n'est pas une donnée manquante : la ligne
    # doit sortir quand même, sinon 37 006 membres deviennent invisibles.
    assert par_pseudo["bob"]["email"] is None
    assert par_pseudo["bob"]["fives"] == 1
    assert par_pseudo["carla"]["fives"] == 0


async def test_tout_arrive_masque(client: httpx.AsyncClient) -> None:
    """Personne n'a demandé à être publié en V2 : le défaut du schéma le dit,
    et rien dans l'import ne le contredit (migration 014)."""
    body = (await client.get("/api/membres")).json()

    assert all(m["masque"] for m in body["items"])


async def test_les_vues_publiques_ne_montrent_personne(conn: psycopg.AsyncConnection) -> None:
    """Le filtre n'est pas un `where` à ne pas oublier : c'est une vue.

    Trois membres, deux tops, et zéro ligne côté public tant que rien n'est
    démasqué — puis exactement le membre démasqué, et son top s'il est public.
    """
    await semer_membres(conn)

    visibles = await (await conn.execute("select count(*) from membre.public_membre")).fetchone()
    assert visibles == (0,)

    await conn.execute("update membre.membre set masque = false where pseudo = 'alice'")
    await conn.execute("update membre.five set visibilite = 'public' where membre_id = 1")

    lignes = await (await conn.execute("select pseudo from membre.public_membre")).fetchall()
    assert lignes == [("alice",)]
    tops = await (await conn.execute("select membre_id from membre.public_five")).fetchall()
    assert tops == [(1,)]


async def test_un_top_public_dun_membre_masque_reste_invisible(
    conn: psycopg.AsyncConnection,
) -> None:
    """Un top de cinq œuvres est déjà signant : le publier sans son auteur ne
    masque rien du tout."""
    await semer_membres(conn)
    await conn.execute("update membre.five set visibilite = 'public'")

    tops = await (await conn.execute("select count(*) from membre.public_five")).fetchone()
    assert tops == (0,)


async def test_recherche_dans_pseudo_et_email(client: httpx.AsyncClient) -> None:
    par_pseudo = (await client.get("/api/membres", params={"q": "ali"})).json()
    par_email = (await client.get("/api/membres", params={"q": "exemple.fr"})).json()

    assert [m["id"] for m in par_pseudo["items"]] == [1]
    assert [m["id"] for m in par_email["items"]] == [1]


async def test_filtre_ceux_qui_ont_un_top(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/membres", params={"avecFives": True})).json()

    assert body["total"] == 2
    assert "carla" not in {m["pseudo"] for m in body["items"]}


async def test_les_tops_gardent_leur_ordre(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/membres/1/fives")).json()

    assert body["membre"]["pseudo"] == "alice"
    assert len(body["fives"]) == 1
    positions = body["fives"][0]["positions"]
    assert [p["rang"] for p in positions] == [1, 2]
    # Le titre vient de la projection TMDB, pas du texte saisi en V1 : le
    # membre avait écrit « Game of Thrones », la fiche dit « Le Trône de fer ».
    # C'est la fiche qui gagne — le titre saisi reste à côté, pour mémoire.
    assert positions[0]["titre"] == "Le Trône de fer"
    assert positions[0]["titreSaisi"] == "Game of Thrones"
    assert positions[0]["pourquoi"] == "pour la fin, évidemment"


async def test_un_membre_sans_top_rend_une_liste_vide(client: httpx.AsyncClient) -> None:
    """Pas un 404 : le membre existe, c'est son top qui n'existe pas."""
    body = (await client.get("/api/membres/3/fives")).json()

    assert body["membre"]["pseudo"] == "carla"
    assert body["fives"] == []


async def test_membre_inconnu(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/membres/99999/fives")).status_code == 404


async def test_tri_inconnu_est_refuse(client: httpx.AsyncClient) -> None:
    """La colonne de tri entre dans un `order by` : elle ne peut pas être liée,
    donc elle est validée contre une liste fermée plutôt qu'échappée."""
    reponse = await client.get("/api/membres", params={"tri": "id; drop table membre.membre"})

    assert reponse.status_code == 400


async def test_les_membres_sont_derriere_la_session(settings: Settings) -> None:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        assert (await http.get("/api/membres")).status_code == 401
