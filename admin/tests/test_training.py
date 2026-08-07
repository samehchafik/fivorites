"""L'entraînement de la notation : dossier, barème, deux juges, poids.

Les appels LLM sont simulés — ces tests vérifient la mécanique (empreintes,
stockage, écarts, ridge), pas le jugement des modèles, qui est précisément ce
que les pages Training mesurent à la main.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb

from conftest import requires_db
from fiv_admin import routes
from fiv_admin.app import create_app
from fiv_admin.config import Settings
from fiv_admin.dossier import build_dossier
from fiv_admin.security import hash_password
from fiv_admin.weights import predict, train_axis

pytestmark = [pytest.mark.integration, requires_db]

PASSWORD = "un mot de passe assez long"
AXES = ["luminosite", "intensite"]


async def seed_series(conn: psycopg.AsyncConnection, id_tmdb: int = 1399) -> None:
    """Une série collectée : fiche avec traduction anglaise, une saison en-US."""
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
        " values (%s, 'Game of Thrones', 400, current_date) on conflict do nothing",
        (id_tmdb,),
    )
    payload = {
        "original_name": "Game of Thrones",
        "first_air_date": "2011-04-17",
        "origin_country": ["US"],
        "number_of_seasons": 2,
        "number_of_episodes": 20,
        "genres": [{"name": "Drama"}, {"name": "Fantasy"}],
        "keywords": {"results": [{"name": "dragon"}, {"name": "civil war"}]},
        "networks": [{"name": "HBO"}],
        "translations": {
            "translations": [
                {
                    "iso_639_1": "en",
                    "iso_3166_1": "US",
                    "data": {
                        "name": "Game of Thrones",
                        "overview": "Noble families fight for the Iron Throne "
                        "while an ancient enemy returns after millennia.",
                    },
                }
            ]
        },
    }
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'tv', %s, 'fr-FR', 200, %s, sha256(%s::bytea))",
        (str(id_tmdb), Jsonb(payload), str(id_tmdb)),
    )
    season = {
        "season_number": 1,
        "episodes": [
            {
                "episode_number": n,
                "name": f"Episode {n}",
                "overview": f"Winter approaches and alliances shift, chapter {n}.",
            }
            for n in range(1, 6)
        ],
    }
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'tv_season', %s, 'en-US', 200, %s, sha256(%s::bytea))",
        (f"{id_tmdb}/s1", Jsonb(season), f"{id_tmdb}/s1"),
    )


@pytest_asyncio.fixture
async def client(
    conn: psycopg.AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    await conn.execute(
        "insert into admin_user (username, password_hash) values (%s, %s)",
        ("sameh", hash_password(PASSWORD)),
    )
    await seed_series(conn)

    # Les juges simulés : OpenAI note 7 partout, Haiku 5 — écart constant de 2,
    # facile à vérifier. L'embedding est déterministe par texte.
    async def fake_openai(http, *, api_key, model, prompt, dossier, axes):
        return {
            "model": "gpt-test",
            "scores": {axe: {"score": 7, "confidence": 0.8} for axe in axes},
        }

    async def fake_anthropic(http, *, api_key, model, prompt, dossier, axes):
        return {
            "model": "claude-test",
            "scores": {axe: {"score": 5, "confidence": 0.6} for axe in axes},
        }

    async def fake_embed(http, *, api_key, model, dimensions, text):
        seed = sum(ord(c) for c in text[:64])
        return [((seed + i) % 17) / 17.0 for i in range(8)]

    monkeypatch.setattr(routes.training, "score_openai", fake_openai)
    monkeypatch.setattr(routes.training, "score_anthropic", fake_anthropic)
    monkeypatch.setattr(routes.training, "embed_openai", fake_embed)

    training_settings = settings.model_copy(
        update={"openai_api_key": "sk-test", "anthropic_api_key": "sk-ant-test"}
    )
    app = create_app(training_settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        await http.post("/api/auth/login", json={"username": "sameh", "password": PASSWORD})
        yield http


# ---------------------------------------------------------------- le dossier


async def test_le_dossier_est_anglais_et_deterministe(conn: psycopg.AsyncConnection) -> None:
    await seed_series(conn, 2000)

    premier = await build_dossier(conn, 2000)
    second = await build_dossier(conn, 2000)

    assert premier is not None
    assert "Noble families fight" in premier["text"], "l'overview vient de la traduction en"
    assert "Winter approaches" in premier["text"], "les synopsis d'épisodes en-US sont là"
    assert premier["sha256"] == second["sha256"], "même base, même texte, même empreinte"


async def test_le_dossier_d_une_serie_non_collectee_est_none(
    conn: psycopg.AsyncConnection,
) -> None:
    assert await build_dossier(conn, 999999) is None


# ---------------------------------------------------------------- phase 1


async def test_phase1_note_avec_les_deux_juges_et_mesure_l_ecart(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    reponse = await client.post(
        "/api/training/phase1",
        json={"id": 1399, "rubricVersion": "v1", "prompt": "p" * 60, "axes": AXES},
    )

    assert reponse.status_code == 200
    body = reponse.json()
    assert body["openai"]["scores"]["luminosite"]["score"] == 7
    assert body["haiku"]["scores"]["luminosite"]["score"] == 5
    assert body["gaps"]["perAxis"]["luminosite"] == 2.0
    assert body["gaps"]["mean"] == 2.0

    # Les deux jugements sont stockés, avec l'empreinte du dossier ET du prompt.
    async with conn.cursor() as cur:
        await cur.execute(
            "select count(*), count(distinct modele), count(distinct prompt_sha256)"
            " from notation.score where id_tmdb = 1399"
        )
        lignes, modeles, prompts = await cur.fetchone()
    assert lignes == len(AXES) * 2
    assert modeles == 2
    assert prompts == 1


async def test_phase1_refuse_un_bareme_inconnu(client: httpx.AsyncClient) -> None:
    reponse = await client.post(
        "/api/training/phase1",
        json={"id": 1399, "rubricVersion": "vX", "prompt": "p" * 60, "axes": AXES},
    )
    assert reponse.status_code == 404


async def test_une_nouvelle_version_de_bareme_ne_s_ecrase_pas(
    client: httpx.AsyncClient,
) -> None:
    corps = {"version": "v-test", "prompt": "p" * 60, "axes": AXES}
    assert (await client.post("/api/training/rubrics", json=corps)).status_code == 201
    assert (await client.post("/api/training/rubrics", json=corps)).status_code == 409


# ---------------------------------------------------------------- phase 2


async def test_les_poids_exigent_un_minimum_d_oeuvres(client: httpx.AsyncClient) -> None:
    reponse = await client.post("/api/training/weights/train", json={"rubricVersion": "v1"})
    assert reponse.status_code == 409
    assert "phase 1" in reponse.json()["detail"]


async def test_entrainement_puis_prediction_interne(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    """Le circuit complet : des notes en base → des poids → une prédiction.

    Sur un barème réduit aux deux axes du test : entraîner `v1` (six axes)
    avec des notes sur deux marquerait les quatre autres « skipped », ce qui
    est le comportement voulu mais pas ce que ce test mesure.
    """
    creation = await client.post(
        "/api/training/rubrics",
        json={"version": "v-poids", "prompt": "p" * 60, "axes": AXES},
    )
    assert creation.status_code == 201

    # Douze œuvres notées directement en base (passer douze fois par phase1
    # testerait surtout la patience du juge simulé).
    for n in range(12):
        id_tmdb = 3000 + n
        await seed_series(conn, id_tmdb)
        async with conn.cursor() as cur:
            for axe in AXES:
                await cur.execute(
                    "insert into notation.score (id_tmdb, axe, valeur, confiance,"
                    " rubric_version, modele, input_sha256, prompt_sha256)"
                    " values (%s, %s, %s, 0.8, 'v-poids', 'gpt-test', 'sha-in', 'sha-p')",
                    (id_tmdb, axe, 4 + (n % 5)),
                )

    entrainement = await client.post(
        "/api/training/weights/train", json={"rubricVersion": "v-poids"}
    )
    assert entrainement.status_code == 200
    bilan = entrainement.json()
    assert bilan["works"] == 12
    assert all(axe["trainedOn"] == 12 for axe in bilan["axes"])

    prediction = await client.post(
        "/api/training/phase2", json={"id": 1399, "rubricVersion": "v-poids"}
    )
    assert prediction.status_code == 200
    body = prediction.json()
    for axe in AXES:
        assert 1.0 <= body["internal"][axe]["score"] <= 10.0

    # La prédiction interne est stockée sous son propre nom de modèle.
    async with conn.cursor() as cur:
        await cur.execute(
            "select count(*) from notation.score where id_tmdb = 1399 and modele = 'interne-ridge'"
        )
        assert (await cur.fetchone())[0] == len(AXES)


async def test_phase2_sans_poids_explique_le_prealable(client: httpx.AsyncClient) -> None:
    reponse = await client.post("/api/training/phase2", json={"id": 1399, "rubricVersion": "v1"})
    assert reponse.status_code == 409
    assert "poids" in reponse.json()["detail"]


# ---------------------------------------------------------------- la ridge


def test_la_ridge_apprend_une_relation_lineaire() -> None:
    """Sur un signal propre, la régression doit le retrouver — c'est le
    contrat minimal avant de lui confier des axes de goût."""
    vectors = [[float(i), float(i % 3)] for i in range(30)]
    values = [1.0 + 0.25 * v[0] for v in vectors]

    poids = train_axis("test", vectors, values)

    assert poids.trained_on == 30
    assert poids.mae_fit < 0.5
    assert abs(predict([20.0, 1.0], poids.intercept, poids.coef) - 6.0) < 1.0


def test_la_prediction_est_bornee_a_l_echelle() -> None:
    assert predict([1000.0], 0.0, [1.0]) == 10.0
    assert predict([-1000.0], 0.0, [1.0]) == 1.0
