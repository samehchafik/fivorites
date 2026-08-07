"""L'entraînement de la notation — les pages Training 1 et Training 2.

C'est l'exception assumée à « l'admin n'écrit pas » : elle écrit dans le schéma
`notation`, qui lui appartient le temps de l'entraînement — le barème s'édite
ici, les notes s'y accumulent, les poids s'y règlent. Elle n'écrit toujours
rien dans `sourcing`.

Phase 1 — stabiliser le barème. Une œuvre, un prompt éditable, deux juges :
OpenAI note, Haiku contre-note. Si les deux divergent au-delà du bruit, c'est
le prompt qui est ambigu — on le corrige et on rejoue. Chaque appel est stocké
avec l'empreinte du dossier ET du prompt : rien n'est comparable sans ça.

Phase 2 — régler les poids. La régression interne prédit les axes depuis
l'embedding du dossier ; on la confronte aux notes LLM. Divergence forte →
réentraîner (le bouton) ; divergence au niveau du bruit → les poids tiennent.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from fiv_admin.deps import Config, Conn, CurrentUser
from fiv_admin.dossier import build_dossier
from fiv_admin.llm import LlmError, embed_openai, score_anthropic, score_openai
from fiv_admin.weights import predict, train_axis

router = APIRouter()

# Le nom du « modèle » sous lequel les prédictions internes sont rangées dans
# `notation.score` — jamais mélangées aux notes LLM.
INTERNAL_MODEL = "interne-ridge"

# En dessous, entraîner n'a pas de sens : plus de bruit que de signal.
MIN_TRAINING_WORKS = 10


def _prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


async def _rubric(conn: Any, version: str) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select version, prompt, axes, note, created_at"
            " from notation.rubric where version = %s",
            (version,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"barème inconnu : {version}")
    return row


async def _store_scores(
    conn: Any,
    *,
    id_tmdb: int,
    scores: dict[str, dict[str, Any]],
    rubric_version: str,
    modele: str,
    input_sha256: str,
    prompt_sha256: str,
) -> None:
    async with conn.cursor() as cur:
        for axe, entry in scores.items():
            await cur.execute(
                """
                insert into notation.score
                    (id_tmdb, axe, valeur, confiance, rubric_version, modele,
                     input_sha256, prompt_sha256)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_tmdb,
                    axe,
                    entry.get("score"),
                    entry.get("confidence"),
                    rubric_version,
                    modele,
                    input_sha256,
                    prompt_sha256,
                ),
            )


def _gaps(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]], axes: list[str]
) -> dict[str, Any]:
    """Les écarts par axe, et leur moyenne sur les axes notés des deux côtés."""
    per_axis: dict[str, float | None] = {}
    diffs: list[float] = []
    for axe in axes:
        a, b = left.get(axe, {}).get("score"), right.get(axe, {}).get("score")
        if a is None or b is None:
            per_axis[axe] = None
        else:
            gap = abs(float(a) - float(b))
            per_axis[axe] = gap
            diffs.append(gap)
    return {
        "perAxis": per_axis,
        "mean": round(sum(diffs) / len(diffs), 2) if diffs else None,
        "scored": len(diffs),
    }


# ---------------------------------------------------------------- le dossier


@router.get("/training/works/{work_id}/dossier")
async def dossier(user: CurrentUser, conn: Conn, work_id: int) -> dict[str, Any]:
    built = await build_dossier(conn, work_id)
    if built is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"aucune fiche collectée pour {work_id} — impossible de construire un dossier.",
        )
    return built


# ---------------------------------------------------------------- le barème


class RubricIn(BaseModel):
    version: str = Field(min_length=1, max_length=60)
    prompt: str = Field(min_length=50)
    axes: list[str] = Field(min_length=1, max_length=16)
    note: str | None = None


@router.get("/training/rubrics")
async def rubrics(user: CurrentUser, conn: Conn) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select version, prompt, axes, note, created_at"
            " from notation.rubric order by created_at desc"
        )
        return list(await cur.fetchall())


@router.post("/training/rubrics", status_code=status.HTTP_201_CREATED)
async def save_rubric(user: CurrentUser, conn: Conn, body: RubricIn) -> dict[str, Any]:
    """Une nouvelle version de barème. Jamais d'écrasement : changer une ancre
    change toutes les notes qui en découlent, la version EST la provenance."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into notation.rubric (version, prompt, axes, note)
            values (%s, %s, %s, %s)
            on conflict (version) do nothing
            returning version
            """,
            (body.version, body.prompt, Jsonb(body.axes), body.note),
        )
        created = await cur.fetchone()
    if created is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"le barème {body.version} existe déjà — choisir un nouveau nom de version.",
        )
    return {"version": body.version}


# ---------------------------------------------------------------- phase 1


class Phase1In(BaseModel):
    id: int
    rubricVersion: str
    # Le prompt réellement envoyé — celui de l'éditeur, sauvé ou non. Son
    # empreinte accompagne chaque note : un essai non sauvé reste traçable.
    prompt: str = Field(min_length=50)
    axes: list[str] = Field(min_length=1, max_length=16)


@router.post("/training/phase1")
async def phase1(user: CurrentUser, conn: Conn, settings: Config, body: Phase1In) -> dict[str, Any]:
    """Une œuvre, deux juges, l'écart par axe. Le cœur de la boucle manuelle."""
    if not settings.openai_api_key or not settings.anthropic_api_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "OPENAI_API_KEY et ANTHROPIC_API_KEY doivent être renseignées dans le .env "
            "de l'admin pour lancer un entraînement.",
        )
    await _rubric(conn, body.rubricVersion)

    built = await build_dossier(conn, body.id)
    if built is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"série {body.id} non collectée")
    if not built["enough"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"dossier trop maigre ({built['chars']} caractères) — noter cette série "
            "produirait des nombres sans valeur. L'enrichir d'abord (enrich --id).",
        )

    async with httpx.AsyncClient() as http:
        try:
            openai_result, haiku_result = await asyncio.gather(
                score_openai(
                    http,
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    prompt=body.prompt,
                    dossier=built["text"],
                    axes=body.axes,
                ),
                score_anthropic(
                    http,
                    api_key=settings.anthropic_api_key,
                    model=settings.anthropic_model,
                    prompt=body.prompt,
                    dossier=built["text"],
                    axes=body.axes,
                ),
            )
        except LlmError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    prompt_sha = _prompt_sha(body.prompt)
    for result in (openai_result, haiku_result):
        await _store_scores(
            conn,
            id_tmdb=body.id,
            scores=result["scores"],
            rubric_version=body.rubricVersion,
            modele=result["model"],
            input_sha256=built["sha256"],
            prompt_sha256=prompt_sha,
        )

    return {
        "id": body.id,
        "dossier": {key: built[key] for key in ("sha256", "chars", "sections", "title")},
        "openai": openai_result,
        "haiku": haiku_result,
        "gaps": _gaps(openai_result["scores"], haiku_result["scores"], body.axes),
    }


@router.get("/training/works/{work_id}/scores")
async def work_scores(user: CurrentUser, conn: Conn, work_id: int) -> list[dict[str, Any]]:
    """L'historique des notes d'une œuvre — tous modèles, tous barèmes."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select axe, valeur, confiance, rubric_version, modele, scored_at
            from notation.score where id_tmdb = %s
            order by scored_at desc, axe
            limit 400
            """,
            (work_id,),
        )
        return list(await cur.fetchall())


# ---------------------------------------------------------------- phase 2


async def _embedding(
    conn: Any, settings: Any, http: httpx.AsyncClient, built: dict[str, Any]
) -> list[float]:
    """L'embedding du dossier, depuis le cache si le texte n'a pas changé."""
    embedder = f"{settings.openai_embed_model}@{settings.embed_dimensions}"
    async with conn.cursor() as cur:
        await cur.execute(
            "select vector from notation.embedding"
            " where id_tmdb = %s and input_sha256 = %s and embedder = %s",
            (built["idTmdb"], built["sha256"], embedder),
        )
        row = await cur.fetchone()
    if row is not None:
        return row[0]

    vector = await embed_openai(
        http,
        api_key=settings.openai_api_key,
        model=settings.openai_embed_model,
        dimensions=settings.embed_dimensions,
        text=built["text"],
    )
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into notation.embedding (id_tmdb, input_sha256, embedder, vector)
            values (%s, %s, %s, %s) on conflict do nothing
            """,
            (built["idTmdb"], built["sha256"], embedder, Jsonb(vector)),
        )
    return vector


class TrainIn(BaseModel):
    rubricVersion: str


@router.post("/training/weights/train")
async def train_weights(
    user: CurrentUser, conn: Conn, settings: Config, body: TrainIn
) -> dict[str, Any]:
    """Réentraîne la régression sur TOUTES les notes OpenAI du barème.

    Toujours sur l'historique complet, jamais sur le dernier lot seul : les
    poids capitalisent, ils ne suivent pas la mode du dernier échantillon.
    """
    if not settings.openai_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "OPENAI_API_KEY absente du .env admin.")
    rubric = await _rubric(conn, body.rubricVersion)
    axes: list[str] = rubric["axes"]

    # La note courante de chaque œuvre : la plus récente par (œuvre, axe),
    # modèle OpenAI seulement — le contre-juge n'entraîne pas.
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select distinct on (id_tmdb, axe) id_tmdb, axe, valeur
            from notation.score
            where rubric_version = %s and modele not in (%s) and modele not like 'claude%%'
              and valeur is not null
            order by id_tmdb, axe, scored_at desc
            """,
            (body.rubricVersion, INTERNAL_MODEL),
        )
        rows = await cur.fetchall()

    by_work: dict[int, dict[str, float]] = {}
    for row in rows:
        by_work.setdefault(row["id_tmdb"], {})[row["axe"]] = float(row["valeur"])
    if len(by_work) < MIN_TRAINING_WORKS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(by_work)} œuvre(s) notée(s) sur ce barème — il en faut au moins "
            f"{MIN_TRAINING_WORKS}. La phase 1 nourrit la phase 2.",
        )

    # Les embeddings de chaque œuvre notée, dossier reconstruit à l'identique.
    embedder = f"{settings.openai_embed_model}@{settings.embed_dimensions}"
    vectors: dict[int, list[float]] = {}
    async with httpx.AsyncClient() as http:
        for id_tmdb in by_work:
            built = await build_dossier(conn, id_tmdb)
            if built is None:
                continue
            try:
                vectors[id_tmdb] = await _embedding(conn, settings, http, built)
            except LlmError as exc:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    trained: list[dict[str, Any]] = []
    async with conn.cursor() as cur:
        for axe in axes:
            pairs = [
                (vectors[id_tmdb], scores[axe])
                for id_tmdb, scores in by_work.items()
                if axe in scores and id_tmdb in vectors
            ]
            if len(pairs) < MIN_TRAINING_WORKS:
                trained.append({"axe": axe, "trainedOn": len(pairs), "skipped": True})
                continue
            result = train_axis(axe, [p[0] for p in pairs], [p[1] for p in pairs])
            await cur.execute(
                """
                insert into notation.weights
                    (rubric_version, axe, intercept, coef, embedder, trained_on, mae_fit)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (rubric_version, axe) do update set
                    intercept = excluded.intercept,
                    coef = excluded.coef,
                    embedder = excluded.embedder,
                    trained_on = excluded.trained_on,
                    mae_fit = excluded.mae_fit,
                    trained_at = now()
                """,
                (
                    body.rubricVersion,
                    axe,
                    result.intercept,
                    Jsonb(result.coef),
                    embedder,
                    result.trained_on,
                    result.mae_fit,
                ),
            )
            trained.append({"axe": axe, "trainedOn": result.trained_on, "maeFit": result.mae_fit})

    return {"rubricVersion": body.rubricVersion, "works": len(by_work), "axes": trained}


class Phase2In(BaseModel):
    id: int
    rubricVersion: str
    # Noter aussi avec OpenAI dans la foulée : c'est la « vérification avec le
    # LLM » de la boucle — comparer l'interne à une note fraîche, pas à une
    # note d'il y a trois barèmes.
    runLlm: bool = False


@router.post("/training/phase2")
async def phase2(user: CurrentUser, conn: Conn, settings: Config, body: Phase2In) -> dict[str, Any]:
    """La prédiction interne face aux notes LLM, œuvre par œuvre."""
    if not settings.openai_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "OPENAI_API_KEY absente du .env admin.")
    rubric = await _rubric(conn, body.rubricVersion)
    axes: list[str] = rubric["axes"]

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select axe, intercept, coef, trained_on, mae_fit, trained_at"
            " from notation.weights where rubric_version = %s",
            (body.rubricVersion,),
        )
        weight_rows = {row["axe"]: row for row in await cur.fetchall()}
    if not weight_rows:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "aucun poids entraîné pour ce barème — lancer d'abord l'entraînement "
            "(il faut au moins 10 œuvres notées en phase 1).",
        )

    built = await build_dossier(conn, body.id)
    if built is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"série {body.id} non collectée")

    async with httpx.AsyncClient() as http:
        try:
            vector = await _embedding(conn, settings, http, built)
            llm_result: dict[str, Any] | None = None
            if body.runLlm:
                llm_result = await score_openai(
                    http,
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    prompt=rubric["prompt"],
                    dossier=built["text"],
                    axes=axes,
                )
        except LlmError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    internal = {
        axe: {
            "score": predict(vector, row["intercept"], row["coef"]),
            "trainedOn": row["trained_on"],
            "maeFit": row["mae_fit"],
        }
        for axe, row in weight_rows.items()
    }
    await _store_scores(
        conn,
        id_tmdb=body.id,
        scores={
            axe: {"score": entry["score"], "confidence": None} for axe, entry in internal.items()
        },
        rubric_version=body.rubricVersion,
        modele=INTERNAL_MODEL,
        input_sha256=built["sha256"],
        prompt_sha256=_prompt_sha(rubric["prompt"]),
    )

    if llm_result is not None:
        await _store_scores(
            conn,
            id_tmdb=body.id,
            scores=llm_result["scores"],
            rubric_version=body.rubricVersion,
            modele=llm_result["model"],
            input_sha256=built["sha256"],
            prompt_sha256=_prompt_sha(rubric["prompt"]),
        )
        llm_scores = llm_result["scores"]
        llm_origin = {"model": llm_result["model"], "fresh": True}
    else:
        # À défaut d'une note fraîche : la dernière note OpenAI stockée.
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                select distinct on (axe) axe, valeur, confiance, modele, scored_at
                from notation.score
                where id_tmdb = %s and rubric_version = %s
                  and modele <> %s and modele not like 'claude%%'
                order by axe, scored_at desc
                """,
                (body.id, body.rubricVersion, INTERNAL_MODEL),
            )
            stored = await cur.fetchall()
        llm_scores = {
            row["axe"]: {
                "score": float(row["valeur"]) if row["valeur"] is not None else None,
                "confidence": float(row["confiance"]) if row["confiance"] is not None else None,
            }
            for row in stored
        }
        llm_origin = (
            {"model": stored[0]["modele"], "fresh": False, "scoredAt": stored[0]["scored_at"]}
            if stored
            else None
        )

    internal_scores = {axe: {"score": entry["score"]} for axe, entry in internal.items()}
    return {
        "id": body.id,
        "dossier": {key: built[key] for key in ("sha256", "chars", "title")},
        "internal": internal,
        "llm": {"scores": llm_scores, "origin": llm_origin},
        "gaps": _gaps(internal_scores, llm_scores, axes) if llm_scores else None,
    }
