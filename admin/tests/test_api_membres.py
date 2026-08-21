"""Les membres et leurs tops, vus du navigateur."""

from __future__ import annotations

import collections
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio

from conftest import requires_db
from fiv_admin.app import create_app
from fiv_admin.config import Settings
from fiv_admin.deps import current_user
from fiv_admin.graphe import Graphe
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


# ---------------------------------------------------------------------------
# Le graphe du membre
# ---------------------------------------------------------------------------


def _reponse(champs: list[str], lignes: list[list[Any]]) -> dict[str, Any]:
    return {"data": {"fields": champs, "values": lignes}}


def _graphe_simule(reponses: dict[str, dict[str, Any]]) -> Graphe:
    """Un Neo4j de papier : chaque motif reconnu dans l'instruction rend ses
    lignes. Ce qui est testé ici est la composition — le Cypher lui-même ne se
    vérifie que contre un vrai serveur."""

    def handler(request: httpx.Request) -> httpx.Response:
        statement = json.loads(request.content)["statement"]
        for motif, valeurs in reponses.items():
            if motif in statement:
                return httpx.Response(202, json=valeurs)
        return httpx.Response(202, json=_reponse([], []))

    graphe = Graphe("http://neo4j.test", "neo4j", "x")
    graphe._http = httpx.AsyncClient(
        base_url="http://neo4j.test", transport=httpx.MockTransport(handler)
    )
    return graphe


VOISINAGE = {
    "FIV_CITE]->(o:FivOeuvre)": _reponse(
        ["oeuvreId", "titre", "annee", "affiche", "univers", "rang", "periode"],
        [
            [10, "Le Trône de fer", 2011, "/got.jpg", "series", 1, "life"],
            [11, "Breaking Bad", 2008, None, "series", 2, "life"],
        ],
    ),
    "FivPersonne)-[r]->": _reponse(
        ["oeuvreId", "cle", "nom", "photo", "role"],
        [
            [10, "tmdb:22970", "Peter Dinklage", "/pd.jpg", "FIV_JOUE_DANS"],
            [11, "tmdb:17419", "Bryan Cranston", None, "FIV_JOUE_DANS"],
            # La même personne sur deux œuvres : un seul nœud, deux arêtes.
            [11, "tmdb:22970", "Peter Dinklage", "/pd.jpg", "FIV_JOUE_DANS"],
        ],
    ),
    "<-[:FIV_CITE]-(v:FivMembre)": _reponse(
        ["membreId", "partagees", "communes"],
        [[2, [10, 11], 2], [3, [10], 1]],
    ),
    "WHERE NOT reco.oeuvreId IN": _reponse(
        ["oeuvreId", "titre", "annee", "affiche", "univers", "voisins", "force", "par"],
        [[12, "Six Feet Under", 2001, None, "series", 2, 4.5, [2, 3]]],
    ),
}


@pytest_asyncio.fixture
async def client_graphe(
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
        app.state.graphe = _graphe_simule(VOISINAGE)
        await http.post("/api/auth/login", json={"username": "sameh", "password": PASSWORD})
        yield http


async def test_le_graphe_compose_les_trois_couches(client_graphe: httpx.AsyncClient) -> None:
    body = (await client_graphe.get("/api/membres/1/graphe")).json()

    types = collections.Counter(n["type"] for n in body["noeuds"])
    assert types == {"moi": 1, "oeuvre": 2, "personne": 2, "voisin": 2, "suggestion": 1}
    assert body["projete"] is True


async def test_une_personne_sur_deux_oeuvres_est_un_seul_noeud(
    client_graphe: httpx.AsyncClient,
) -> None:
    """C'est tout l'intérêt du dessin : ce qui relie deux œuvres entre elles.
    Deux nœuds pour Peter Dinklage, et le lien ne se verrait plus."""
    body = (await client_graphe.get("/api/membres/1/graphe")).json()

    dinklage = [n for n in body["noeuds"] if n["libelle"] == "Peter Dinklage"]
    assert len(dinklage) == 1
    aretes = [a for a in body["aretes"] if a["de"] == "personne:tmdb:22970"]
    assert {a["vers"] for a in aretes} == {"oeuvre:10", "oeuvre:11"}


async def test_le_voisin_porte_ses_oeuvres_communes(client_graphe: httpx.AsyncClient) -> None:
    body = (await client_graphe.get("/api/membres/1/graphe")).json()

    voisins = {n["libelle"]: n for n in body["noeuds"] if n["type"] == "voisin"}
    # Le pseudo vient de Postgres, jamais du graphe : le nœud Neo4j n'en porte
    # pas. C'est l'administration qui rapproche, derrière sa session.
    assert "bob" in voisins
    assert voisins["bob"]["communes"] == 2


async def test_les_univers_presents_sont_nommes(client_graphe: httpx.AsyncClient) -> None:
    """Le front construit ses filtres là-dessus, et ne connaît aucune liste.

    Le jour où les livres entrent dans `MEDIA`, le bouton doit apparaître sans
    qu'une ligne du front change — d'où le libellé rendu par le serveur.
    """
    body = (await client_graphe.get("/api/membres/1/graphe")).json()

    assert body["univers"] == [{"code": "series", "label": "Séries", "oeuvres": 3}]


async def test_la_suggestion_vient_des_voisins_et_pas_de_lui(
    client_graphe: httpx.AsyncClient,
) -> None:
    """Le second degré : ce que les voisins citent et que lui ne cite pas.

    Chaque arête part du voisin, jamais du membre — c'est ce qui répond à
    « pourquoi celle-là ? » sur le dessin. Une œuvre suggérée sans arête
    flotterait sans raison visible.
    """
    body = (await client_graphe.get("/api/membres/1/graphe")).json()

    suggestion = next(n for n in body["noeuds"] if n["type"] == "suggestion")
    assert suggestion["libelle"] == "Six Feet Under"
    assert suggestion["voisins"] == 2

    vers_elle = [a for a in body["aretes"] if a["vers"] == suggestion["id"]]
    assert {a["de"] for a in vers_elle} == {"membre:2", "membre:3"}
    assert not any(a["de"] == "membre:1" for a in vers_elle)


async def test_sans_voisin_aucune_suggestion(
    conn: psycopg.AsyncConnection, settings: Settings
) -> None:
    """La quatrième requête ne part pas : `UNWIND` sur une liste vide ne rend
    rien, mais l'aller-retour, lui, coûte quand même."""
    sans_voisins = dict(VOISINAGE)
    sans_voisins["<-[:FIV_CITE]-(v:FivMembre)"] = _reponse(
        ["membreId", "partagees", "communes"], []
    )

    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        app.state.graphe = _graphe_simule(sans_voisins)
        app.dependency_overrides[current_user] = lambda: "sameh"
        body = (await http.get("/api/membres/1/graphe")).json()

    assert not [n for n in body["noeuds"] if n["type"] in ("voisin", "suggestion")]


async def test_un_membre_hors_du_graphe_le_dit(
    conn: psycopg.AsyncConnection, settings: Settings
) -> None:
    """`projete: false` distingue « pas encore projeté » de « ne cite rien » —
    le front n'a pas à deviner lequel des deux il regarde."""
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        app.state.graphe = _graphe_simule({})
        app.dependency_overrides[current_user] = lambda: "sameh"
        body = (await http.get("/api/membres/1/graphe")).json()

    assert body == {"membre": {"id": 1}, "noeuds": [], "aretes": [], "projete": False}


async def test_sans_neo4j_la_route_dit_ce_qui_manque(
    conn: psycopg.AsyncConnection, settings: Settings
) -> None:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        app.state.graphe = None
        app.dependency_overrides[current_user] = lambda: "sameh"
        reponse = await http.get("/api/membres/1/graphe")

    assert reponse.status_code == 503
    assert "NEO4J_URL" in reponse.json()["detail"]
