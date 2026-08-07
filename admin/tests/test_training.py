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
from fiv_admin.llm import LlmError
from fiv_admin.security import hash_password
from fiv_admin.stills import select_images
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
        "images": {
            "backdrops": [
                {"file_path": "/moins-vote.jpg", "vote_count": 2},
                {"file_path": "/plus-vote.jpg", "vote_count": 9},
            ]
        },
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
        "overview": "Two great houses collide while winter gathers in the north.",
        "episodes": [
            {
                "episode_number": n,
                "name": f"Episode {n}",
                "overview": f"Winter approaches and alliances shift, chapter {n}.",
                "still_path": f"/s1e{n}.jpg",
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
    assert (
        "MATERIAL: overview, 1 season overview(s), 5 sampled episode synopses." in premier["text"]
    )


async def test_le_dossier_signale_la_matiere_disponible(conn: psycopg.AsyncConnection) -> None:
    """Le signal qui manquait : sans lui, un synopsis de trois phrases peut se
    lire comme un dossier complet — c'est exactement ce qui a fait diverger
    Haiku (null, prudent) et OpenAI (des scores confiants) sur une série dont
    le seul brut collecté est la fiche."""
    id_tmdb = 2200
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
        " values (%s, 'Matiere maigre', 1, current_date)",
        (id_tmdb,),
    )
    payload = {
        "original_name": "Matiere maigre",
        "translations": {
            "translations": [
                {
                    "iso_639_1": "en",
                    "iso_3166_1": "US",
                    "data": {"name": "Thin Material", "overview": "A short premise, nothing more."},
                }
            ]
        },
    }
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'tv', %s, 'fr-FR', 200, %s, sha256(%s::bytea))",
        (str(id_tmdb), Jsonb(payload), str(id_tmdb)),
    )

    built = await build_dossier(conn, id_tmdb)

    assert built is not None
    assert "MATERIAL: overview." in built["text"], (
        "rien d'autre que l'overview : le dit sans détour"
    )


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

    # Et le journal garde l'essai entier sur une ligne : prompt en clair,
    # fiche brute référencée, les deux verdicts côte à côte.
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, raw_source_id, prompt, openai, claude, claude_at"
            " from notation.training_run where id_tmdb = 1399"
        )
        runs = await cur.fetchall()
    assert len(runs) == 1
    run_id, raw_id, run_prompt, openai_json, claude_json, claude_at = runs[0]
    assert body["runId"] == run_id
    assert raw_id is not None, "la fiche brute qui a nourri le dossier est référencée"
    assert run_prompt == "p" * 60
    assert openai_json["scores"]["luminosite"]["score"] == 7
    assert claude_json["scores"]["luminosite"]["score"] == 5
    assert claude_at is not None


async def test_phase1_sans_cle_anthropic_note_avec_openai_seul(
    conn: psycopg.AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le contre-jugement est facultatif : sans clé Anthropic, OpenAI note et
    le contre-juge est l'humain, via claude.ai et la contre-note manuelle."""
    await conn.execute(
        "insert into admin_user (username, password_hash) values (%s, %s)",
        ("sameh", hash_password(PASSWORD)),
    )
    await seed_series(conn)

    async def fake_openai(http, *, api_key, model, prompt, dossier, axes):
        return {
            "model": "gpt-test",
            "scores": {axe: {"score": 6, "confidence": 0.7} for axe in axes},
        }

    monkeypatch.setattr(routes.training, "score_openai", fake_openai)

    app = create_app(
        settings.model_copy(update={"openai_api_key": "sk-test", "anthropic_api_key": ""})
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        await http.post("/api/auth/login", json={"username": "sameh", "password": PASSWORD})

        reponse = await http.post(
            "/api/training/phase1",
            json={"id": 1399, "rubricVersion": "v1", "prompt": "p" * 60, "axes": AXES},
        )
        assert reponse.status_code == 200
        body = reponse.json()
        assert body["haiku"] is None
        assert body["gaps"] is None

        # La contre-note manuelle prend le relais, même provenance.
        manuel = await http.post(
            "/api/training/manual",
            json={
                "id": 1399,
                "rubricVersion": "v1",
                "prompt": "p" * 60,
                "scores": {"luminosite": {"score": 4}, "intensite": {"score": None}},
            },
        )
        assert manuel.status_code == 200
        corps = manuel.json()
        assert corps["stored"] == 2
        assert corps["modele"] == "claude-web-manuel"
        assert corps["runId"] is not None

    async with conn.cursor() as cur:
        await cur.execute(
            "select modele, count(*) from notation.score where id_tmdb = 1399"
            " group by modele order by modele"
        )
        assert await cur.fetchall() == [("claude-web-manuel", 2), ("gpt-test", len(AXES))]

    # Le journal : l'essai OpenAI (sans contre-note à sa création, faute de
    # clé) a été complété après coup par la contre-note manuelle — une seule
    # ligne, les deux verdicts dessus.
    async with conn.cursor() as cur:
        await cur.execute(
            "select openai, claude, claude_at from notation.training_run where id_tmdb = 1399"
        )
        runs = await cur.fetchall()
    assert len(runs) == 1
    openai_json, claude_json, claude_at = runs[0]
    assert openai_json["scores"]["luminosite"]["score"] == 6
    assert claude_json["model"] == "claude-web-manuel"
    assert claude_json["scores"]["luminosite"]["score"] == 4
    assert claude_json["scores"]["intensite"]["score"] is None
    assert claude_at is not None


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
    assert bilan["weightsId"] is not None

    # Le journal des poids : une ligne par prompt — réentraîner le même
    # prompt redate sa ligne au lieu d'en empiler une seconde.
    second = await client.post("/api/training/weights/train", json={"rubricVersion": "v-poids"})
    assert second.json()["weightsId"] == bilan["weightsId"]
    async with conn.cursor() as cur:
        await cur.execute(
            "select prompt, weights, works from notation.training_weights"
            " where rubric_version = 'v-poids'"
        )
        journaux = await cur.fetchall()
    assert len(journaux) == 1
    prompt_journal, poids_json, works = journaux[0]
    assert prompt_journal == "p" * 60
    assert works == 12
    assert set(poids_json.keys()) == set(AXES)
    assert all("intercept" in entry and "coef" in entry for entry in poids_json.values())

    prediction = await client.post(
        "/api/training/phase2", json={"id": 1399, "rubricVersion": "v-poids"}
    )
    assert prediction.status_code == 200
    assert prediction.json()["runId"] is not None, "le vecteur généré entre au journal"

    # Le journal porte le vecteur interne, à côté des verdicts.
    async with conn.cursor() as cur:
        await cur.execute(
            "select interne, interne_at from notation.training_run"
            " where id_tmdb = 1399 and rubric_version = 'v-poids'"
        )
        interne, interne_at = await cur.fetchone()
    assert set(interne.keys()) == set(AXES)
    assert all(1.0 <= entry["score"] <= 10.0 for entry in interne.values())
    assert interne_at is not None
    assert prediction.status_code == 200
    body = prediction.json()
    assert body["weights"]["works"] == 12, "la version de poids utilisée est identifiée"
    for axe in AXES:
        assert 1.0 <= body["internal"][axe]["score"] <= 10.0

    # La prédiction interne est stockée sous son propre nom de modèle.
    async with conn.cursor() as cur:
        await cur.execute(
            "select count(*) from notation.score where id_tmdb = 1399 and modele = 'interne-ridge'"
        )
        assert (await cur.fetchone())[0] == len(AXES)


async def test_l_entrainement_regenere_les_oeuvres_deja_jugees(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    """Des poids neufs périment les prédictions faites avec les anciens : tout
    essai portant un verdict OpenAI est régénéré dans la foulée."""
    creation = await client.post(
        "/api/training/rubrics",
        json={"version": "v-regen", "prompt": "r" * 60, "axes": AXES},
    )
    assert creation.status_code == 201

    for n in range(12):
        id_tmdb = 5000 + n
        await seed_series(conn, id_tmdb)
        async with conn.cursor() as cur:
            for axe in AXES:
                await cur.execute(
                    "insert into notation.score (id_tmdb, axe, valeur, confiance,"
                    " rubric_version, modele, input_sha256, prompt_sha256)"
                    " values (%s, %s, %s, 0.8, 'v-regen', 'gpt-test', 'sha-in', 'sha-p')",
                    (id_tmdb, axe, 3 + (n % 6)),
                )
            # Seules les trois premières ont un essai journalisé avec verdict.
            if n < 3:
                await cur.execute(
                    "insert into notation.training_run (id_tmdb, rubric_version, prompt,"
                    " dossier_sha256, openai) values (%s, 'v-regen', %s, 'sha-in', %s)",
                    (id_tmdb, "r" * 60, Jsonb({"model": "gpt-test", "scores": {}})),
                )

    entrainement = await client.post(
        "/api/training/weights/train", json={"rubricVersion": "v-regen"}
    )

    assert entrainement.status_code == 200
    assert entrainement.json()["generated"] == 3, "une génération par essai portant un verdict"

    async with conn.cursor() as cur:
        await cur.execute(
            "select count(*) from notation.training_run"
            " where rubric_version = 'v-regen' and interne is not null"
        )
        assert (await cur.fetchone())[0] == 3
        # Les neuf autres n'ont pas d'essai : rien n'a été inventé pour elles.
        await cur.execute(
            "select count(*) from notation.training_run where rubric_version = 'v-regen'"
        )
        assert (await cur.fetchone())[0] == 3


async def test_phase2_sans_poids_explique_le_prealable(client: httpx.AsyncClient) -> None:
    reponse = await client.post("/api/training/phase2", json={"id": 1399, "rubricVersion": "v1"})
    assert reponse.status_code == 409
    assert "poids" in reponse.json()["detail"]


async def test_le_journal_se_relit_du_plus_recent_au_plus_ancien(
    client: httpx.AsyncClient,
) -> None:
    """Recharger la page ne perd rien : les essais se relisent du journal."""
    for _ in range(2):
        essai = await client.post(
            "/api/training/phase1",
            json={"id": 1399, "rubricVersion": "v1", "prompt": "p" * 60, "axes": AXES},
        )
        assert essai.status_code == 200

    reponse = await client.get("/api/training/works/1399/runs")
    assert reponse.status_code == 200
    runs = reponse.json()
    assert len(runs) == 2
    assert runs[0]["id"] > runs[1]["id"], "le plus récent d'abord"
    assert runs[0]["prompt"] == "p" * 60
    assert runs[0]["openai"]["scores"]["luminosite"]["score"] == 7
    assert runs[0]["claude"]["scores"]["luminosite"]["score"] == 5
    assert runs[0]["interne"] is None, "rien de généré tant que la phase 2 n'est pas passée"


async def test_le_journal_expose_le_vecteur_genere(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    """Training 2 s'affiche à l'ouverture : le vecteur généré se relit du
    journal, sans qu'on ait à recliquer « Générer »."""
    creation = await client.post(
        "/api/training/rubrics",
        json={"version": "v-relu", "prompt": "u" * 60, "axes": AXES},
    )
    assert creation.status_code == 201

    for n in range(12):
        id_tmdb = 6000 + n
        await seed_series(conn, id_tmdb)
        async with conn.cursor() as cur:
            for axe in AXES:
                await cur.execute(
                    "insert into notation.score (id_tmdb, axe, valeur, confiance,"
                    " rubric_version, modele, input_sha256, prompt_sha256)"
                    " values (%s, %s, %s, 0.8, 'v-relu', 'gpt-test', 'sha-in', 'sha-p')",
                    (id_tmdb, axe, 4 + (n % 5)),
                )

    assert (
        await client.post("/api/training/weights/train", json={"rubricVersion": "v-relu"})
    ).status_code == 200
    assert (
        await client.post("/api/training/phase2", json={"id": 1399, "rubricVersion": "v-relu"})
    ).status_code == 200

    # Rien de plus n'est cliqué : le journal porte déjà tout ce qu'il faut.
    reponse = await client.get("/api/training/works/1399/runs")

    assert reponse.status_code == 200
    run = reponse.json()[0]
    assert set(run["interne"].keys()) == set(AXES)
    assert all(1.0 <= entry["score"] <= 10.0 for entry in run["interne"].values())
    assert run["interneAt"] is not None


# ---------------------------------------------------------------- les visuels


def test_la_selection_des_visuels_est_deterministe_et_votee() -> None:
    fiche = {
        "images": {
            "backdrops": [
                {"file_path": "/b.jpg", "vote_count": 1},
                {"file_path": "/a.jpg", "vote_count": 8},
            ]
        }
    }
    seasons = [
        (1, {"episodes": [{"episode_number": 3, "still_path": "/e3.jpg"}]}),
    ]

    premier = select_images(fiche, seasons)
    assert premier == select_images(fiche, seasons), "même brut, même sélection"
    assert premier[0]["url"].endswith("/a.jpg"), "le backdrop le plus voté d'abord"
    assert premier[0]["label"] == "backdrop 1"
    assert premier[-1] == {
        "url": "https://image.tmdb.org/t/p/w780/e3.jpg",
        "kind": "still",
        "label": "S01E03",
    }


async def test_le_dossier_integre_saisons_et_legendes(conn: psycopg.AsyncConnection) -> None:
    await seed_series(conn, 2100)
    async with conn.cursor() as cur:
        for url, kind, label, caption in [
            ("https://image.tmdb.org/t/p/w780/e1.jpg", "still", "S01E01", "bright open field"),
            ("https://image.tmdb.org/t/p/w780/a.jpg", "backdrop", "backdrop 1", "dark castle"),
        ]:
            await cur.execute(
                "insert into notation.media_caption (id_tmdb, url, kind, label, caption, modele)"
                " values (2100, %s, %s, %s, %s, 'gpt-vision-test')",
                (url, kind, label, caption),
            )

    built = await build_dossier(conn, 2100)

    assert built is not None
    assert "MATERIAL: overview, 1 season overview(s), 5 sampled episode synopses," in built["text"]
    assert "2 visual caption(s)." in built["text"]
    assert "SEASON OVERVIEWS:\nSeason 1: Two great houses collide" in built["text"]
    assert "MEDIA (what the official images show" in built["text"]
    assert built["text"].index("backdrop 1: dark castle") < built["text"].index(
        "S01E01: bright open field"
    ), "les backdrops avant les stills — l'ordre de l'index, donc de l'empreinte"
    assert built["sections"]["seasonOverviews"] == 1
    assert built["sections"]["mediaLines"] == 2


async def test_le_dossier_legende_les_visuels_manquants_tout_seul(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La donnée visuelle ne bouge pas : la légende se crée à la première
    lecture du dossier, puis se relit — sans qu'on ait rien à cliquer."""
    appels: list[int] = []

    async def fake_caption(http, *, api_key, model, images):
        appels.append(len(images))
        return {
            "model": "gpt-vision-test",
            "captions": [f"dark moody frame ({image['label']})" for image in images],
        }

    monkeypatch.setattr(routes.training, "caption_openai", fake_caption)

    premier = await client.get("/api/training/works/1399/dossier")
    assert premier.status_code == 200
    assert "dark moody frame (backdrop 1)" in premier.json()["text"]
    assert premier.json()["sections"]["mediaLines"] == 7
    assert appels == [7]

    second = await client.get("/api/training/works/1399/dossier")
    assert second.json()["sha256"] == premier.json()["sha256"], "même dossier, même empreinte"
    assert appels == [7], "les légendes sont relues, jamais repayées"


async def test_le_dossier_se_lit_meme_si_la_vision_echoue(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un modèle de vision en panne ne doit pas rendre une série innotable :
    le dossier se construit, simplement sans section MEDIA."""

    async def fake_caption(http, *, api_key, model, images):
        raise LlmError("OpenAI vision 500 : boom")

    monkeypatch.setattr(routes.training, "caption_openai", fake_caption)

    reponse = await client.get("/api/training/works/1399/dossier")
    assert reponse.status_code == 200
    assert reponse.json()["sections"]["mediaLines"] == 0
    assert "MEDIA (" not in reponse.json()["text"]


async def test_legender_paye_une_fois_puis_relit(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le contrat économique du bouton : un appel vision par image nouvelle,
    zéro pour une image déjà légendée — la légende est figée."""
    appels: list[int] = []

    async def fake_caption(http, *, api_key, model, images):
        appels.append(len(images))
        return {
            "model": "gpt-vision-test",
            "captions": [f"dark moody frame ({image['label']})" for image in images],
        }

    monkeypatch.setattr(routes.training, "caption_openai", fake_caption)

    premier = await client.post("/api/training/works/1399/captions")
    assert premier.status_code == 200
    body = premier.json()
    assert body["total"] == 7, "2 backdrops de la fiche + 5 stills d'épisodes"
    assert body["captioned"] == 7
    assert appels == [7]

    second = await client.post("/api/training/works/1399/captions")
    assert second.status_code == 200
    assert second.json()["captioned"] == 0
    assert second.json()["already"] == 7
    assert appels == [7], "pas de second appel vision : les légendes sont relues, pas repayées"

    built = await build_dossier(conn, 1399)
    assert built is not None
    assert "dark moody frame (backdrop 1)" in built["text"]


async def test_legender_sans_visuel_explique(
    client: httpx.AsyncClient, conn: psycopg.AsyncConnection
) -> None:
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
        " values (2200, 'Sans images', 1, current_date)"
    )
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'tv', '2200', 'fr-FR', 200, %s, sha256('2200'::bytea))",
        (Jsonb({"original_name": "Sans images"}),),
    )

    reponse = await client.post("/api/training/works/2200/captions")
    assert reponse.status_code == 409
    assert "aucun visuel" in reponse.json()["detail"]


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


def test_la_ridge_discrimine_des_embeddings_normalises() -> None:
    """Le bug du premier lot réel : un λ fixé à 10 face à des embeddings de
    norme 1 écrasait ~97 % du signal — treize œuvres très différentes
    recevaient le même vecteur, la moyenne d'entraînement. λ se choisit
    maintenant par validation croisée : sur des vecteurs de ce gabarit, les
    prédictions doivent séparer les deux groupes, pas les confondre."""
    vectors, values = [], []
    for i in range(20):
        sign = 1.0 if i < 10 else -1.0
        v = [0.0] * 8
        v[0] = 0.15 * sign  # le signal, faible comme dans un vrai embedding
        v[1] = 0.98  # la composante partagée qui domine la norme
        v[2 + (i % 5)] = 0.05  # un peu de variation, pour une matrice honnête
        vectors.append(v)
        values.append(8.0 if i < 10 else 3.0)

    poids = train_axis("test", vectors, values)
    preds = [predict(v, poids.intercept, poids.coef) for v in vectors]
    hauts = sum(preds[:10]) / 10
    bas = sum(preds[10:]) / 10

    assert hauts - bas > 3.0, (
        f"les groupes 8 et 3 doivent rester séparés ({hauts:.1f} vs {bas:.1f}) — "
        "des prédictions plates signifient que λ écrase le signal"
    )
    assert poids.mae_loo < 1.0, "la validation croisée doit trouver un λ qui généralise ici"


def test_la_prediction_est_bornee_a_l_echelle() -> None:
    assert predict([1000.0], 0.0, [1.0]) == 10.0
    assert predict([-1000.0], 0.0, [1.0]) == 1.0
