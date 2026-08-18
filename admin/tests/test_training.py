"""L'entraînement de la notation : dossier, barème, deux juges, poids.

Les appels LLM sont simulés — ces tests vérifient la mécanique (empreintes,
stockage, écarts, ridge), pas le jugement des modèles, qui est précisément ce
que les pages Training mesurent à la main.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import AsyncIterator

import httpx
import numpy as np
import psycopg
import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb

from conftest import requires_db
from fiv_admin import routes
from fiv_admin.app import create_app
from fiv_admin.config import Settings
from fiv_admin.dossier import build_dossier
from fiv_admin.embed import MAX_CHARS
from fiv_admin.llm import LOT_EMBEDDING, embed_openai
from fiv_admin.routes.training import (
    PasAssezDOeuvres as PasAssezDOeuvresErreur,
)
from fiv_admin.security import hash_password
from fiv_admin.stills import select_images
from fiv_admin.weights import (
    comparer_modeles,
    predict,
    predictions_ridge,
    train_axis,
    voisins_cosinus,
)

pytestmark = [pytest.mark.integration, requires_db]

PASSWORD = "un mot de passe assez long"
AXES = ["luminosite", "intensite"]


async def seed_series(conn: psycopg.AsyncConnection, id_tmdb: int = 1399) -> int:
    """Une série collectée : fiche avec traduction anglaise, une saison en-US.

    Renvoie son `oeuvre_id` — le pivot sous lequel la notation range tout
    depuis le lot 12. La collecte le crée en même temps que la fiche ; ce seed
    fait la même chose, sans quoi il décrirait une base qui n'existe pas.
    """
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
        " values (%s, 'Game of Thrones', 400, current_date) on conflict do nothing",
        (id_tmdb,),
    )
    await conn.execute(
        "insert into oeuvre (univers, id_tmdb) values ('series', %s) on conflict do nothing",
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
    row = await (
        await conn.execute(
            "select id from oeuvre where univers = 'series' and id_tmdb = %s", (id_tmdb,)
        )
    ).fetchone()
    return row[0]  # type: ignore[index]


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

    # L'encodeur est local et déterministe, mais charger le vrai modèle ONNX
    # coûterait cinq secondes à chaque session de tests pour ne rien vérifier
    # de plus : ces tests portent sur la mécanique, pas sur la qualité des
    # vecteurs. Le simulacre garde la propriété qui compte — même texte, même
    # vecteur — sur laquelle repose le cache.
    def faux_encodeur(texts, *, cache_dir=None):
        vecteurs = []
        for text in texts:
            graine = sum(ord(c) for c in text[:64])
            vecteurs.append([((graine + i) % 17) / 17.0 for i in range(8)])
        return vecteurs

    monkeypatch.setattr(routes.training, "score_openai", fake_openai)
    monkeypatch.setattr(routes.training, "score_anthropic", fake_anthropic)
    monkeypatch.setattr(routes.training, "embed_texts", faux_encodeur)

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


async def test_wikipedia_survit_a_la_troncature_de_l_encodeur(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le cas Docteur House.

    Le juge lit le dossier entier ; l'encodeur le tronque à `MAX_CHARS`, en
    coupant la fin. Tant que Wikipédia fermait le dossier, une série à huit
    saisons de résumés consommait le budget avant d'y arriver : l'article
    n'entrait jamais dans le vecteur, alors même que la série était enrichie et
    que GPT, lui, l'avait lu — 8 en réflexion contre 6,1 prédits.

    On vérifie donc que sur une fiche volumineuse, Wikipédia tient dans ce que
    l'encodeur voit réellement, et que ce qui se fait couper est la liste des
    synopsis.
    """
    id_tmdb = 2300
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
        " values (%s, 'Longue serie', 1, current_date)",
        (id_tmdb,),
    )
    payload = {
        "original_name": "Longue serie",
        "number_of_seasons": 8,
        "translations": {
            "translations": [
                {
                    "iso_639_1": "en",
                    "iso_3166_1": "US",
                    "data": {"name": "Long Show", "overview": "A medical procedural."},
                }
            ]
        },
    }
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'tv', %s, 'fr-FR', 200, %s, sha256(%s::bytea))",
        (str(id_tmdb), Jsonb(payload), str(id_tmdb)),
    )
    # Huit saisons de résumés longs : le gabarit d'un procédural qui dure, et
    # celui qui saturait le budget de l'encodeur.
    for n in range(1, 9):
        saison = {
            "season_number": n,
            "overview": f"Season {n}. " + "A patient arrives with unexplained symptoms. " * 40,
            "episodes": [
                {
                    "episode_number": e,
                    "name": f"Episode {e}",
                    "overview": "The team runs tests and argues about the diagnosis. " * 6,
                }
                for e in range(1, 23)
            ],
        }
        await conn.execute(
            "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
            " payload_sha256) values ('tmdb', 'tv_season', %s, 'en-US', 200, %s,"
            " sha256(%s::bytea))",
            (f"{id_tmdb}/s{n}", Jsonb(saison), f"{id_tmdb}/s{n}"),
        )
    await conn.execute(
        "insert into oeuvre (univers, id_tmdb, titre, annee)"
        " values ('series', %s, 'Long Show', 2004)",
        (id_tmdb,),
    )
    oeuvre = await (
        await conn.execute("select id from oeuvre where id_tmdb = %s", (id_tmdb,))
    ).fetchone()
    await conn.execute(
        "insert into riche_source (oeuvre_id, id_tmdb, source, lang, source_id, content)"
        " values (%s, %s, 'wikipedia', 'en', 'Long Show', %s)",
        (oeuvre[0], id_tmdb, "The themes of the series are ethics and truth. " * 100),  # type: ignore[index]
    )

    built = await build_dossier(conn, id_tmdb)

    assert built is not None
    assert len(built["text"]) > MAX_CHARS, "fiche volontairement hors gabarit"
    vu_par_l_encodeur = built["text"][:MAX_CHARS]
    assert "WIKIPEDIA (en):" in vu_par_l_encodeur, (
        "l'encodeur ne voit pas Wikipédia — la section est reléguée après ce qui déborde"
    )
    assert "ethics and truth" in vu_par_l_encodeur, "l'en-tête ne suffit pas, le texte doit suivre"


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
            " from notation.score s join oeuvre o on o.id = s.oeuvre_id"
            " where o.id_tmdb = 1399"
        )
        lignes, modeles, prompts = await cur.fetchone()
    assert lignes == len(AXES) * 2
    assert modeles == 2
    assert prompts == 1

    # Et le journal garde l'essai entier sur une ligne : prompt en clair,
    # fiche brute référencée, les deux verdicts côte à côte.
    async with conn.cursor() as cur:
        await cur.execute(
            "select t.id, t.raw_source_id, t.prompt, t.openai, t.claude, t.claude_at"
            " from notation.training_run t join oeuvre o on o.id = t.oeuvre_id"
            " where o.id_tmdb = 1399"
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
            "select s.modele, count(*) from notation.score s"
            " join oeuvre o on o.id = s.oeuvre_id where o.id_tmdb = 1399"
            " group by s.modele order by s.modele"
        )
        assert await cur.fetchall() == [("claude-web-manuel", 2), ("gpt-test", len(AXES))]

    # Le journal : l'essai OpenAI (sans contre-note à sa création, faute de
    # clé) a été complété après coup par la contre-note manuelle — une seule
    # ligne, les deux verdicts dessus.
    async with conn.cursor() as cur:
        await cur.execute(
            "select t.openai, t.claude, t.claude_at from notation.training_run t"
            " join oeuvre o on o.id = t.oeuvre_id where o.id_tmdb = 1399"
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
        oeuvre_id = await seed_series(conn, id_tmdb)
        async with conn.cursor() as cur:
            for axe in AXES:
                await cur.execute(
                    "insert into notation.score (oeuvre_id, axe, valeur, confiance,"
                    " rubric_version, modele, input_sha256, prompt_sha256)"
                    " values (%s, %s, %s, 0.8, 'v-poids', 'gpt-test', 'sha-in', 'sha-p')",
                    (oeuvre_id, axe, 4 + (n % 5)),
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
            "select t.interne, t.interne_at from notation.training_run t"
            " join oeuvre o on o.id = t.oeuvre_id"
            " where o.id_tmdb = 1399 and t.rubric_version = 'v-poids'"
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
            "select count(*) from notation.score s join oeuvre o on o.id = s.oeuvre_id"
            " where o.id_tmdb = 1399 and s.modele = 'interne-ridge'"
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
        oeuvre_id = await seed_series(conn, id_tmdb)
        async with conn.cursor() as cur:
            for axe in AXES:
                await cur.execute(
                    "insert into notation.score (oeuvre_id, axe, valeur, confiance,"
                    " rubric_version, modele, input_sha256, prompt_sha256)"
                    " values (%s, %s, %s, 0.8, 'v-regen', 'gpt-test', 'sha-in', 'sha-p')",
                    (oeuvre_id, axe, 3 + (n % 6)),
                )
            # Seules les trois premières ont un essai journalisé avec verdict.
            if n < 3:
                await cur.execute(
                    "insert into notation.training_run (oeuvre_id, rubric_version, prompt,"
                    " dossier_sha256, openai) values (%s, 'v-regen', %s, 'sha-in', %s)",
                    (oeuvre_id, "r" * 60, Jsonb({"model": "gpt-test", "scores": {}})),
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
        oeuvre_id = await seed_series(conn, id_tmdb)
        async with conn.cursor() as cur:
            for axe in AXES:
                await cur.execute(
                    "insert into notation.score (oeuvre_id, axe, valeur, confiance,"
                    " rubric_version, modele, input_sha256, prompt_sha256)"
                    " values (%s, %s, %s, 0.8, 'v-relu', 'gpt-test', 'sha-in', 'sha-p')",
                    (oeuvre_id, axe, 4 + (n % 5)),
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
    oeuvre_id = await seed_series(conn, 2100)
    async with conn.cursor() as cur:
        for url, kind, label, caption in [
            ("https://image.tmdb.org/t/p/w780/e1.jpg", "still", "S01E01", "bright open field"),
            ("https://image.tmdb.org/t/p/w780/a.jpg", "backdrop", "backdrop 1", "dark castle"),
        ]:
            await cur.execute(
                "insert into notation.media_caption"
                " (oeuvre_id, url, kind, label, caption, modele)"
                " values (%s, %s, %s, %s, %s, 'gpt-vision-test')",
                (oeuvre_id, url, kind, label, caption),
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


async def test_lire_un_dossier_ne_declenche_aucune_depense(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ouvrir une fiche ne coûte rien. Le légendage a été automatique un
    temps ; sur un catalogue de cette taille, la facture montait pendant la
    simple consultation. Il se demande maintenant, il ne s'impose plus."""
    appels: list[int] = []

    async def fake_caption(http, *, api_key, model, images):
        appels.append(len(images))
        return {"model": "gpt-vision-test", "captions": ["frame"] * len(images)}

    monkeypatch.setattr(routes.training, "caption_openai", fake_caption)

    reponse = await client.get("/api/training/works/1399/dossier")

    assert reponse.status_code == 200
    assert appels == [], "lire un dossier ne doit appeler aucun modèle de vision"
    assert reponse.json()["sections"]["mediaLines"] == 0


async def test_noter_ne_legende_pas_sans_qu_on_le_demande(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Même règle pour la notation : le juge lit ce qui est en base, et le
    visuel n'entre au dossier que si on a payé pour l'y mettre."""
    appels: list[int] = []

    async def fake_caption(http, *, api_key, model, images):
        appels.append(len(images))
        return {"model": "gpt-vision-test", "captions": ["frame"] * len(images)}

    monkeypatch.setattr(routes.training, "caption_openai", fake_caption)

    essai = await client.post(
        "/api/training/phase1",
        json={"id": 1399, "rubricVersion": "v1", "prompt": "p" * 60, "axes": AXES},
    )

    assert essai.status_code == 200
    assert appels == [], "noter ne doit pas déclencher de légendage"


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
    assert poids.mae_cv < 1.0, "la validation croisée doit trouver un λ qui généralise ici"


def test_la_recalibration_rend_leurs_extremes_aux_predictions() -> None:
    """Le cas Always Sunny : le juge dit 9, la ridge rendait 7. La
    régularisation comprime l'échelle vers la moyenne — pente mesurée entre
    0,49 et 0,68 en production — et la recalibration l'inverse, mesurée sur
    les prédictions hors-pli. On vérifie ici qu'un signal bruité mais réel
    ressort à la bonne amplitude, pas seulement dans le bon ordre."""
    rng = random.Random(7)
    dims, n = 128, 60
    vx, vy = [], []
    for _ in range(n):
        signal = rng.uniform(-1, 1)
        v = [0.0] * dims
        v[0] = 0.1 * signal
        v[1] = 0.95
        for j in range(2, dims):
            v[j] = rng.gauss(0, 0.03)
        vx.append(v)
        vy.append(max(1.0, min(10.0, 5.5 + 3.5 * signal + rng.gauss(0, 0.6))))

    poids = train_axis("test", vx, vy)
    preds = [predict(v, poids.intercept, poids.coef) for v in vx]

    assert poids.pente > 1.0, "la compression existe : la calibration doit s'engager"
    etendue_reelle = max(vy) - min(vy)
    etendue_predite = max(preds) - min(preds)
    assert etendue_predite > 0.7 * etendue_reelle, (
        f"étendue prédite {etendue_predite:.1f} contre réelle {etendue_reelle:.1f} — "
        "les extrêmes restent écrasés malgré la calibration"
    )


def test_la_calibration_vise_la_variance_pas_la_pente() -> None:
    """Le cas Game of Thrones : le juge donne 8 sur quatre dimensions, la
    régression rendait 6 partout, et l'œuvre la plus contrastée du corpus
    ressortait plate.

    La distinction est fine et elle décide de tout. La pente de régression
    `cov(y,p)/var(p)` est celle qui minimise l'erreur quadratique, mais elle
    laisse par construction `sd(prédit) = r · sd(juge)` : avec un r réaliste de
    0,85, il manque encore 15 % d'amplitude *après* correction. Mesuré sur 502
    œuvres, l'écart-type prédit valait 75 à 87 % de celui du juge.

    Ce test échoue avec une calibration sur la pente et passe avec une
    calibration sur l'écart-type. Il compte parce que la distance entre œuvres
    sera un cosine : des vecteurs tassés se ressemblent tous.
    """
    rng = random.Random(21)
    dims, n = 128, 80
    vx, vy = [], []
    for _ in range(n):
        signal = rng.uniform(-1, 1)
        v = [0.0] * dims
        v[0] = 0.1 * signal
        v[1] = 0.95
        for j in range(2, dims):
            v[j] = rng.gauss(0, 0.03)
        vx.append(v)
        # Bruit volontairement large : c'est lui qui fait décrocher r de 1, et
        # donc lui qui sépare les deux calibrations.
        vy.append(max(1.0, min(10.0, 5.5 + 3.0 * signal + rng.gauss(0, 1.2))))

    poids = train_axis("test", vx, vy)
    preds = [predict(v, poids.intercept, poids.coef) for v in vx]

    ecart_juge = statistics.pstdev(vy)
    ecart_predit = statistics.pstdev(preds)
    assert ecart_predit > 0.9 * ecart_juge, (
        f"écart-type prédit {ecart_predit:.2f} contre {ecart_juge:.2f} chez le juge "
        f"({ecart_predit / ecart_juge:.0%}) — une calibration sur la pente s'arrête à r, "
        "il faut viser la variance"
    )


def test_la_ridge_ne_recopie_pas_le_juge() -> None:
    """Le bug du second lot réel : 41 œuvres, 256 dimensions, et une régression
    qui rendait EXACTEMENT les notes d'OpenAI — maeFit à 0,003. Avec moins
    d'exemples que de dimensions, un λ minuscule interpole les données ; la
    forme fermée du LOO calculait alors 0/0 et désignait ce λ-là. Ici on tient
    le seul critère qui ne ment pas : ce que le modèle fait sur des œuvres
    qu'il n'a jamais vues."""
    rng = random.Random(12)
    dims, n_train, n_test = 256, 41, 20

    def echantillon(k: int) -> tuple[list[list[float]], list[float]]:
        vecteurs, notes = [], []
        for _ in range(k):
            signal = rng.uniform(-1, 1)
            v = [0.0] * dims
            v[0] = 0.12 * signal
            v[1] = 0.97
            for j in range(2, dims):
                v[j] = rng.gauss(0, 0.02)
            vecteurs.append(v)
            # Une vraie note : une part de signal, une part de bruit.
            notes.append(max(1.0, min(10.0, 5.5 + 3.0 * signal + rng.gauss(0, 0.4))))
        return vecteurs, notes

    vx, vy = echantillon(n_train)
    tx, ty = echantillon(n_test)

    poids = train_axis("test", vx, vy)

    # Le seul critère qui ne ment pas : ce que le modèle fait sur des œuvres
    # qu'il n'a jamais vues. Le MAE d'ajustement, lui, peut être excellent
    # pour de mauvaises raisons — c'est précisément le piège d'origine.
    erreurs = [
        abs(predict(v, poids.intercept, poids.coef) - y) for v, y in zip(tx, ty, strict=True)
    ]
    dehors = sum(erreurs) / len(erreurs)
    assert dehors < 2.0, f"erreur {dehors:.2f} sur des œuvres jamais vues — λ trop faible"


def test_la_prediction_est_bornee_a_l_echelle() -> None:
    assert predict([1000.0], 0.0, [1.0]) == 10.0
    assert predict([-1000.0], 0.0, [1.0]) == 1.0


async def test_le_dossier_porte_les_critiques_de_spectateurs(
    conn: psycopg.AsyncConnection,
) -> None:
    """Le cas Lucifer : le juge la note 6 en joie, le modèle interne 3,1.

    Le dossier ne racontait qu'un policier surnaturel — la comédie est dans le
    jeu, pas dans l'intrigue, et aucune section ne la portait. `reviews` est
    pourtant collecté par TMDB depuis le premier jour : c'est la seule matière
    qui parle du ton plutôt que des faits.

    Les plus longues d'abord : une critique de trois lignes dit « super
    série », une de trois paragraphes dit pourquoi.
    """
    id_tmdb = 2400
    await conn.execute(
        "insert into tmdb_catalog (id, original_name, popularity, exported_on)"
        " values (%s, 'Serie drole', 1, current_date)",
        (id_tmdb,),
    )
    payload = {
        "original_name": "Serie drole",
        "reviews": {
            "results": [
                {"author": "court", "content": "Bien."},
                {"author": "long", "content": "Hilarious from start to finish. " * 30},
                {"author": "moyen", "content": "Genuinely funny and warm. " * 10},
            ]
        },
        "translations": {
            "translations": [
                {
                    "iso_639_1": "en",
                    "iso_3166_1": "US",
                    "data": {"name": "Funny Show", "overview": "A detective solves murders."},
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
    assert "VIEWER REVIEWS" in built["text"]
    assert "Hilarious from start to finish" in built["text"]
    assert "Genuinely funny" in built["text"], "les deux plus longues sont retenues"
    assert "Bien." not in built["text"], "la plus courte est écartée : elle ne dit rien du ton"
    assert "2 viewer review(s)" in built["text"], "MATERIAL doit annoncer ce qui est là"


def test_les_modeles_non_lineaires_passent_un_controle_que_la_ridge_echoue() -> None:
    """Le garde-fou de la comparaison elle-même.

    Quatre amas notés en XOR : aucun hyperplan ne les sépare, donc la ridge ne
    peut qu'en rendre la moyenne. Les trois autres doivent réussir — sinon un
    « ils perdent tous » ne voudrait rien dire, puisqu'on ne saurait pas
    distinguer un plafond réel d'une implémentation défaillante.

    Ce test a déjà servi deux fois. Il a montré que le réseau plafonnait avec
    une descente à inertie, corrigée par Adam ; puis qu'il apprenait son pli
    par cœur parce qu'on réduisait les entrées, ce qui amplifiait les
    dimensions de bruit jusqu'au niveau du signal.
    """
    rng = random.Random(3)
    vecteurs, notes = [], []
    for cx, cy, note in ((1.0, 1.0, 8.0), (-1.0, -1.0, 8.0), (1.0, -1.0, 2.0), (-1.0, 1.0, 2.0)):
        for _ in range(30):
            v = [rng.gauss(0, 0.05) for _ in range(32)]
            v[0] = cx + rng.gauss(0, 0.15)
            v[1] = cy + rng.gauss(0, 0.15)
            vecteurs.append(v)
            notes.append(note + rng.gauss(0, 0.3))

    bilan = comparer_modeles(axe="test", vectors=vecteurs, values=notes)

    assert bilan["oeuvres"] == 120
    ridge = bilan["ridge"]
    assert ridge["maeCv"] > 2.0, "la ridge ne peut pas voir un XOR : c'est le point du test"
    for nom in ("voisins", "noyau", "reseau"):
        modele = bilan[nom]
        assert modele, f"{nom} n'a rien renvoye"
        assert modele["maeCv"] < 1.0, (
            f"{nom} rend {modele['maeCv']} sur une structure qu'il devrait lire — "
            "la comparaison mesurerait l'implementation, pas la question posee"
        )
        assert modele["correlation"] > 0.9, f"{nom} ne retrouve pas l'ordre"


def test_voisins_cosinus_reste_dans_le_groupe() -> None:
    """Trois familles nettement separees : le voisinage ne doit pas les melanger.

    C'est le controle du diagnostic de Lucifer. Si le voisinage se trompe sur
    des groupes construits pour etre evidents, alors un voisinage decevant sur
    les vraies donnees ne dirait rien de l'encodeur — il dirait seulement que
    la fonction est fausse, et la conclusion « l'information n'est pas dans la
    representation » ne tiendrait pas.
    """
    rng = random.Random(5)
    familles: dict[int, int] = {}
    vecteurs: list[list[float]] = []
    for famille in range(3):
        base = [rng.gauss(0, 1) for _ in range(32)]
        for _ in range(20):
            familles[len(vecteurs)] = famille
            vecteurs.append([b + rng.gauss(0, 0.12) for b in base])

    for depart in (0, 25, 45):
        proches = voisins_cosinus(vecteurs, depart, 6)
        assert len(proches) == 6
        assert all(i != depart for i, _ in proches), "une oeuvre est sa propre voisine"
        assert all(familles[i] == familles[depart] for i, _ in proches), (
            "le voisinage melange des familles clairement separees"
        )
        assert proches == sorted(proches, key=lambda p: -p[1]), "voisins non tries"


def test_predictions_ridge_reproduit_la_ligne_du_tableau() -> None:
    """Œuvre par œuvre, la meme chose que la colonne « ridge » resume.

    Le diagnostic croise cette erreur avec la longueur du dossier. Si elle ne
    venait pas exactement du modele de production — meme λ, meme pente, memes
    bornes — la correlation porterait sur une autre regression que celle qu'on
    cherche a expliquer.
    """
    rng = random.Random(11)
    direction = [rng.gauss(0, 1) for _ in range(24)]
    vecteurs: list[list[float]] = []
    notes: list[float] = []
    for _ in range(90):
        v = [rng.gauss(0, 1) for _ in range(24)]
        vecteurs.append(v)
        brut = sum(a * b for a, b in zip(direction, v, strict=True)) / 6.0
        notes.append(min(10.0, max(1.0, 5.5 + brut + rng.gauss(0, 0.4))))

    poids = train_axis("test", vecteurs, notes)
    preds = predictions_ridge(vecteurs, notes, poids)
    vus = [(float(p), y) for p, y in zip(preds, notes, strict=True) if not math.isnan(float(p))]
    assert vus, "aucune prediction hors-pli"
    mae = sum(abs(p - y) for p, y in vus) / len(vus)

    tableau = comparer_modeles(axe="test", vectors=vecteurs, values=notes)
    assert round(mae, 3) == tableau["ridge"]["maeCv"]


async def test_embed_openai_recolle_les_vecteurs_dans_l_ordre_demande() -> None:
    """Les lots peuvent revenir melanges ; l'appariement doit tenir quand meme.

    L'API ne garantit pas l'ordre de `data`, seulement le champ `index`. Un
    appariement fonde sur le rang de la liste collerait des vecteurs aux
    mauvaises oeuvres — et une regression sur des paires melangees ne ressemble
    pas a un bug, elle ressemble a un mauvais encodeur. On aurait conclu contre
    le candidat au lieu de conclure contre le code.
    """
    import json

    textes = [f"dossier {i}" for i in range(120)]
    tailles: list[int] = []

    def repondre(request: httpx.Request) -> httpx.Response:
        lot = json.loads(request.content)["input"]
        tailles.append(len(lot))
        data = [
            {"index": rang, "embedding": [float(int(t.split()[1])), 0.0]}
            for rang, t in enumerate(lot)
        ]
        # Renvoye a l'envers, exactement ce que le contrat autorise.
        return httpx.Response(200, json={"data": list(reversed(data))})

    async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as http:
        vecteurs = await embed_openai(
            http, api_key="cle", model="text-embedding-3-large", textes=textes
        )

    assert tailles == [LOT_EMBEDDING, LOT_EMBEDDING, 20], "les lots ne sont pas ceux annonces"
    assert [v[0] for v in vecteurs] == [float(i) for i in range(120)]


def test_encodeur_api_distingue_les_deux_chemins() -> None:
    """Le prefixe decide du chemin, le suffixe de la dimension demandee."""
    from fiv_admin.routes.training import _encodeur_api, cout_encodeurs

    assert _encodeur_api("jinaai/jina-embeddings-v2-small-en") is None
    assert _encodeur_api("openai/text-embedding-3-large") == ("text-embedding-3-large", None)
    assert _encodeur_api("openai/text-embedding-3-large@512") == ("text-embedding-3-large", 512)

    # Un candidat local ne coute rien, et la troncature borne la depense : un
    # dossier de cinquante mille caracteres n'est facture que sur douze mille.
    textes = ["x" * 50_000] * 100
    local = cout_encodeurs(("jinaai/jina-embeddings-v2-small-en",), textes)
    api = cout_encodeurs(("openai/text-embedding-3-large",), textes)
    assert local == 0.0
    assert api == pytest.approx(100 * MAX_CHARS / 4 / 1_000_000 * 0.13)


def test_le_balayage_groupe_rend_les_memes_predictions_que_lambda_par_lambda() -> None:
    """Sortir la SVD de la boucle sur λ ne doit rien changer aux resultats.

    C'est une optimisation, pas un changement de methode : les coefficients
    valent `V^T·((s/(s²+λ))·(U^T y))`, seul le facteur d'echelle depend de λ.
    Les operations sont les memes et dans le meme ordre, donc l'egalite doit
    tenir au bit pres — un ecart, meme minuscule, signalerait qu'on a change
    le calcul en croyant l'accelerer.
    """
    from fiv_admin.weights import (
        LAMBDA_GRID,
        _predictions_croisees,
        _predictions_par_lambda,
    )

    rng = np.random.default_rng(3)
    x = rng.normal(0, 1, (80, 40))
    y = rng.normal(5, 2, 80)

    groupe = _predictions_par_lambda(x, y, LAMBDA_GRID, 10)
    for lam in LAMBDA_GRID:
        seul = _predictions_croisees(x, y, lam, 10)
        assert np.array_equal(groupe[lam], seul, equal_nan=True), f"divergence a lambda={lam}"

    # Le meme controle sur le chemin `x_eval`, qui sert a mesurer ce qu'une
    # section du dossier apporte : il applique le modele a d'autres vecteurs
    # que ceux qui l'ont ajuste, et c'est la que l'oubli du recentrage se
    # payerait.
    x_autre = x + rng.normal(0, 0.1, x.shape)
    groupe_eval = _predictions_par_lambda(x, y, LAMBDA_GRID, 10, x_eval=x_autre)
    for lam in LAMBDA_GRID:
        seul = _predictions_croisees(x, y, lam, 10, x_eval=x_autre)
        assert np.array_equal(groupe_eval[lam], seul, equal_nan=True)


async def seed_film(conn: psycopg.AsyncConnection, id_tmdb: int = 1399) -> int:
    """Un film collecte, volontairement au MEME id_tmdb qu'une serie.

    C'est le piege que les deux catalogues TMDB tendent : ils numerotent
    separement, donc le film 1399 et la serie 1399 coexistent sans etre la
    meme oeuvre. Un seed qui prendrait deux ids differents ne testerait rien.
    """
    await conn.execute(
        "insert into tmdb_catalog (univers, id, original_name, popularity, exported_on)"
        " values ('movies', %s, 'Fight Club', 300, current_date) on conflict do nothing",
        (id_tmdb,),
    )
    await conn.execute(
        "insert into oeuvre (univers, id_tmdb) values ('movies', %s) on conflict do nothing",
        (id_tmdb,),
    )
    payload = {
        "original_title": "Fight Club",
        "release_date": "1999-10-15",
        "runtime": 139,
        "tagline": "Mischief. Mayhem. Soap.",
        "production_countries": [{"iso_3166_1": "US"}],
        "production_companies": [{"name": "Fox 2000 Pictures"}],
        "genres": [{"name": "Drama"}, {"name": "Thriller"}],
        # Cote film TMDB nomme la liste `keywords`, pas `results`.
        "keywords": {"keywords": [{"name": "insomnia"}, {"name": "dual identity"}]},
        "translations": {
            "translations": [
                {
                    "iso_639_1": "en",
                    "iso_3166_1": "US",
                    "data": {
                        "title": "Fight Club",
                        "tagline": "Mischief. Mayhem. Soap.",
                        "overview": "An insomniac office worker and a soap maker "
                        "form an underground fight club that evolves into much more.",
                    },
                }
            ]
        },
    }
    await conn.execute(
        "insert into raw_source (source, kind, source_id, lang, http_status, payload,"
        " payload_sha256) values ('tmdb', 'movie', %s, 'fr-FR', 200, %s, sha256(%s::bytea))",
        (str(id_tmdb), Jsonb(payload), str(id_tmdb) + "movie"),
    )
    row = await (
        await conn.execute(
            "select id from oeuvre where univers = 'movies' and id_tmdb = %s", (id_tmdb,)
        )
    ).fetchone()
    return int(row[0])


async def test_le_dossier_film_ne_prend_pas_la_fiche_de_la_serie_de_meme_id(
    conn: psycopg.AsyncConnection,
) -> None:
    """Meme id_tmdb, deux univers : chaque dossier doit rester chez lui.

    C'est l'erreur qui ne se verrait pas. Un film servi avec la fiche d'une
    serie produit un dossier parfaitement plausible — titre, genres, synopsis,
    tout est la — qui decrit simplement une autre oeuvre. La note serait
    fausse sans qu'aucune verification ne s'en plaigne.
    """
    await seed_series(conn, 1399)
    oeuvre_film = await seed_film(conn, 1399)

    serie = await build_dossier(conn, 1399)
    film = await build_dossier(conn, 1399, univers="movies")
    assert serie is not None and film is not None

    assert "Game of Thrones" in serie["text"]
    assert "Fight Club" in film["text"]
    assert "Game of Thrones" not in film["text"]
    assert serie["sha256"] != film["sha256"], "deux oeuvres, une seule empreinte"
    assert film["oeuvreId"] == oeuvre_film
    assert film["univers"] == "movies"


async def test_le_dossier_film_lit_les_champs_que_tmdb_nomme_autrement(
    conn: psycopg.AsyncConnection,
) -> None:
    """`title`/`original_title` et `keywords.keywords`, pas les noms des series.

    Lire la mauvaise cle ne leve aucune erreur : elle rend un dossier sans
    titre et sans mots-cles, qui passe tous les controles et note a cote.
    """
    await seed_film(conn, 550)
    film = await build_dossier(conn, 550, univers="movies")
    assert film is not None

    assert film["title"] == "Fight Club"
    assert "KEYWORDS: insomnia, dual identity" in film["text"]
    # Les faits propres au format : duree et sortie, ni saison ni chaine.
    assert "139 minutes" in film["text"]
    assert "released 1999-10-15" in film["text"]
    assert "seasons" not in film["text"]
    assert "SEASON OVERVIEWS" not in film["text"]
    assert "EPISODE SYNOPSES" not in film["text"]
    # La tagline est souvent la phrase la plus explicite sur le ton vise.
    assert "TAGLINE: Mischief. Mayhem. Soap." in film["text"]


async def test_le_secours_local_est_etiquete_et_ecarte_de_l_entrainement(
    conn: psycopg.AsyncConnection, settings: Settings
) -> None:
    """API demandee, cle absente : le vecteur sort du modele local, et il le dit.

    C'est la panne qu'il ne faut pas rendre silencieuse. Un vecteur de secours
    vit dans un autre espace que les poids entraines sur l'API ; le servir
    quand meme rendrait six nombres plausibles et faux. On prefere un dossier
    lisible, un vecteur correctement etiquete, et un entrainement qui refuse.
    """
    from fiv_admin.embed import EMBEDDER, etiquette
    from fiv_admin.routes.training import EncodeurIndisponible, encoder_dossier, entrainer_poids

    await seed_series(conn, 2400)
    built = await build_dossier(conn, 2400)
    assert built is not None

    # Meme reglage que la production, mais sans cle : le secours doit prendre
    # le relais plutot que de faire echouer la lecture du dossier.
    degrade = settings.model_copy(
        update={"embedder": "openai/text-embedding-3-large@512", "openai_api_key": ""}
    )
    vecteur, label = await encoder_dossier(conn, degrade, built)
    assert len(vecteur) == 512
    assert label == EMBEDDER, "le secours doit se ranger sous SON etiquette"
    assert label != etiquette(degrade.embedder)

    # Et le vecteur ne doit pas etre range sous l'etiquette de production :
    # sinon un encodage ulterieur, correct celui-la, le trouverait en cache.
    async with conn.cursor() as cur:
        await cur.execute(
            "select count(*) from notation.embedding where embedder = %s",
            (etiquette(degrade.embedder),),
        )
        assert (await cur.fetchone())[0] == 0

    # L'entrainement refuse plutot que de rendre « zero axe entraine », qui
    # ressemblerait a un succes et laisserait les poids d'hier en place.
    rubric = {"version": "empreinte-v3", "prompt": "p" * 60, "axes": ["joie"]}
    with pytest.raises((EncodeurIndisponible, PasAssezDOeuvresErreur)):
        await entrainer_poids(conn, degrade, rubric)


def test_l_etiquette_distingue_les_trois_familles_d_encodeurs() -> None:
    """Nom fastembed, API, modele maison : trois formes, trois etiquettes.

    C'est elle qui empeche le melange, et le melange serait silencieux : deux
    espaces vectoriels dans une meme regression ne levent aucune erreur, ils
    rendent des poids qui ne veulent rien dire.
    """
    from fiv_admin.embed import EMBEDDER, MODEL_NAME, etiquette

    assert etiquette(MODEL_NAME) == EMBEDDER
    assert etiquette("openai/text-embedding-3-large@512") == "text-embedding-3-large@512"
    assert etiquette("BAAI/bge-small-en-v1.5") == "BAAI/bge-small-en-v1.5"

    # Le chemin ne doit PAS entrer dans l'etiquette : l'eleve distille vit a
    # des emplacements differents selon la machine, et un chemin en dur ferait
    # recalculer tout le cache au premier demenagement.
    assert etiquette("local:/opt/models/eleve-distille") == "eleve-distille"
    assert etiquette("local:/srv/autre/chemin/eleve-distille") == "eleve-distille"


async def test_l_export_du_corpus_ecarte_les_dossiers_perimes(
    conn: psycopg.AsyncConnection,
) -> None:
    """Un dossier modifie depuis son encodage ne doit pas entrer dans le corpus.

    Le texte n'est pas stocke, seul son sha l'est. Une oeuvre enrichie depuis
    l'encodage a change de dossier : son vecteur ne lui correspond plus, et la
    paire enseignerait a l'eleve une correspondance qui n'a jamais existe.
    """
    import io
    import json as json_

    from fiv_admin.routes.training import exporter_corpus

    oeuvre = await seed_series(conn, 2500)
    built = await build_dossier(conn, 2500)
    assert built is not None

    async def ranger(sha: str) -> None:
        await conn.execute(
            "insert into notation.embedding (oeuvre_id, input_sha256, embedder, vector)"
            " values (%s, %s, 'prof@512', %s) on conflict do nothing",
            (oeuvre, sha, Jsonb([0.1] * 512)),
        )

    # Le bon sha : la paire doit sortir.
    await ranger(built["sha256"])
    sortie = io.StringIO()
    bilan = await exporter_corpus(conn, "prof@512", sortie)
    assert bilan["ecrites"] == 1
    assert bilan["perimees"] == 0
    paire = json_.loads(sortie.getvalue().strip())
    assert paire["idTmdb"] == 2500
    assert paire["text"] == built["text"]
    assert len(paire["vector"]) == 512

    # Le meme vecteur sous un sha qui ne correspond a rien : ecarte.
    await conn.execute("delete from notation.embedding where embedder = 'prof@512'")
    await ranger("0" * 64)
    sortie = io.StringIO()
    bilan = await exporter_corpus(conn, "prof@512", sortie)
    assert bilan["ecrites"] == 0
    assert bilan["perimees"] == 1
    assert sortie.getvalue() == ""


async def test_la_liste_a_noter_ne_melange_pas_les_univers(
    conn: psycopg.AsyncConnection,
) -> None:
    """Un film et une serie au meme id_tmdb : chaque liste doit rester chez elle.

    `works_a_noter` lisait `tv_card` en dur ; la version films doit lire
    `movie_card` ET porter l'univers dans ses jointures — sans quoi le pivot
    d'un film serait celui de la serie de meme identifiant, et le journal
    marquerait la mauvaise oeuvre comme jugee.
    """
    from fiv_admin.routes.training import works_a_noter

    await seed_series(conn, 1399)
    await seed_film(conn, 1399)
    # Les listes lisent les projections, pas le brut.
    from fiv_admin.catalog import refresh_cards

    await refresh_cards(conn)

    series = await works_a_noter(conn, "empreinte-v3", 10, filtres=False)
    films = await works_a_noter(conn, "empreinte-v3", 10, filtres=False, univers="movies")

    assert [c["id_tmdb"] for c in series] == [1399]
    assert [c["id_tmdb"] for c in films] == [1399]
    assert series[0]["titre"] == "Game of Thrones"
    assert films[0]["titre"] == "Fight Club"
    assert series[0]["oeuvre_id"] != films[0]["oeuvre_id"], (
        "meme pivot pour deux univers : le journal marquerait la mauvaise oeuvre"
    )


async def test_les_notes_ne_fusionnent_pas_le_film_et_la_serie_de_meme_id(
    conn: psycopg.AsyncConnection,
) -> None:
    """Deux oeuvres, meme id_tmdb, notees differemment : deux entrees, pas une.

    L'agregation historique par `id_tmdb` aurait fusionne le film 550 et la
    serie 550 en une seule « oeuvre » : la note la plus recente aurait ecrase
    l'autre, et les poids se seraient entraines sur des paires dossier/note
    depareillees — sans erreur, sans avertissement.
    """
    from fiv_admin.routes.training import MIN_TRAINING_WORKS, _notes_du_bareme

    async def noter(oeuvre: int, valeur: float) -> None:
        await conn.execute(
            "insert into notation.score (oeuvre_id, axe, valeur, confiance, rubric_version,"
            " modele, input_sha256, prompt_sha256)"
            " values (%s, 'joie', %s, 0.9, 'v1', 'gpt-test', 'a', 'b')",
            (oeuvre, valeur),
        )

    oeuvre_serie = await seed_series(conn, 550)
    oeuvre_film = await seed_film(conn, 550)
    await noter(oeuvre_serie, 8.0)
    await noter(oeuvre_film, 2.0)
    # De quoi passer le seuil : le sujet du test est la fusion, pas le seuil.
    for n in range(MIN_TRAINING_WORKS):
        await noter(await seed_series(conn, 9000 + n), 5.0)

    by_work, infos = await _notes_du_bareme(conn, "v1")

    assert by_work[oeuvre_serie]["joie"] == 8.0
    assert by_work[oeuvre_film]["joie"] == 2.0
    assert infos[oeuvre_serie] == (550, "series")
    assert infos[oeuvre_film] == (550, "movies")


def test_les_ancres_du_bareme_se_relisent_depuis_le_prompt() -> None:
    """Les 24 oeuvres de reference vivent dans le texte du prompt.

    C'est le juge qui les lit ; les relire ici permet de poser au systeme la
    question la plus elementaire qu'on ne lui avait jamais posee — reproduit-il
    ses propres definitions ? Un parseur qui rendrait un dictionnaire vide
    ferait passer la mesure pour reussie sans avoir rien compare.
    """
    from fiv_admin.routes.training import _ancres_du_bareme, _normaliser

    prompt = (
        "blabla\n"
        "1. joie — Joy. How much lightness.\n"
        "   Anchors: Chernobyl = 1, Mad Men = 4, Parks and Recreation = 10.\n"
        "2. peur — Fear. How much dread.\n"
        "   Anchors: Downton Abbey = 1, The Haunting of Hill House = 10.\n"
    )
    ancres = _ancres_du_bareme(prompt)

    assert set(ancres) == {"joie", "peur"}
    assert ancres["joie"]["chernobyl"] == 1.0
    assert ancres["joie"]["mad men"] == 4.0
    assert ancres["joie"]["parks and recreation"] == 10.0
    # L'article initial saute : le catalogue ecrit « Haunting of Hill House »
    # aussi souvent que « The Haunting of Hill House ».
    assert ancres["peur"]["haunting of hill house"] == 10.0

    assert _normaliser("The Good Place") == "good place"
    assert _normaliser("Grey's Anatomy") == "greys anatomy"
    assert _normaliser("  24  ") == "24"
