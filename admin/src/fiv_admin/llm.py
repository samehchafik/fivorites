"""Les juges : OpenAI (le noteur), Anthropic Haiku (le contre-juge).

Deux familles de modèles, exprès. La chaîne d'entraînement descend entièrement
d'OpenAI (notes, embeddings, poids) : un juge d'une autre famille est le seul à
pouvoir détecter un biais que toute la lignée partagerait. Haiku ne note pas la
masse — il contredit, ou pas.

La sortie est **contrainte** au schéma dans les deux cas : six entiers et six
confiances, jamais de prose à reparser. Les bornes 1-10 sont vérifiées ici (les
sorties structurées d'Anthropic ne portent pas de contraintes numériques), et
un score hors bornes est ramené dedans plutôt que rejeté — un 0 ou un 11 est
une maladresse d'échelle, pas une absence de jugement.
"""

from __future__ import annotations

from typing import Any

import httpx

OPENAI_BASE = "https://api.openai.com/v1"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"

# Assez pour un dossier de ~2 000 tokens et une réponse de ~300 : un appel qui
# dépasse ça est un appel parti en vrille, pas un appel lent.
TIMEOUT = httpx.Timeout(90.0, connect=10.0)


class LlmError(RuntimeError):
    """Un appel de notation a échoué — fournisseur, statut et détail dans le message."""


def scores_schema(axes: list[str]) -> dict[str, Any]:
    """Le schéma JSON de la réponse : par axe, un score 1-10 (ou null) et une
    confiance 0-1. Pas de bornes numériques dans le schéma — Anthropic ne les
    supporte pas en sortie structurée — elles sont appliquées au retour."""
    axis = {
        "type": "object",
        "properties": {
            "score": {"type": ["integer", "null"]},
            "confidence": {"type": "number"},
        },
        "required": ["score", "confidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {axe: axis for axe in axes},
        "required": list(axes),
        "additionalProperties": False,
    }


def _clamp(parsed: dict[str, Any], axes: list[str]) -> dict[str, dict[str, float | int | None]]:
    result: dict[str, dict[str, float | int | None]] = {}
    for axe in axes:
        entry = parsed.get(axe) or {}
        score = entry.get("score")
        score = int(min(10, max(1, round(score)))) if isinstance(score, int | float) else None
        confidence = entry.get("confidence")
        confidence = (
            round(min(1.0, max(0.0, float(confidence))), 2)
            if isinstance(confidence, int | float)
            else 0.0
        )
        result[axe] = {"score": score, "confidence": confidence}
    return result


async def score_openai(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: str,
    dossier: str,
    axes: list[str],
) -> dict[str, Any]:
    """Une notation par l'API OpenAI, sortie contrainte au schéma."""
    response = await http.post(
        f"{OPENAI_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": dossier},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "axis_scores",
                    "strict": True,
                    "schema": scores_schema(axes),
                },
            },
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise LlmError(f"OpenAI {response.status_code} : {response.text[:300]}")

    body = response.json()
    try:
        import json

        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, ValueError) as exc:
        raise LlmError(f"réponse OpenAI illisible : {exc}") from exc

    return {"model": body.get("model", model), "scores": _clamp(parsed, axes)}


async def score_anthropic(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: str,
    dossier: str,
    axes: list[str],
) -> dict[str, Any]:
    """La même notation par l'API Anthropic — le contre-juge."""
    response = await http.post(
        f"{ANTHROPIC_BASE}/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        json={
            "model": model,
            "max_tokens": 1500,
            "system": prompt,
            "messages": [{"role": "user", "content": dossier}],
            "output_config": {"format": {"type": "json_schema", "schema": scores_schema(axes)}},
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise LlmError(f"Anthropic {response.status_code} : {response.text[:300]}")

    body = response.json()
    try:
        import json

        text = next(block["text"] for block in body["content"] if block.get("type") == "text")
        parsed = json.loads(text)
    except (StopIteration, KeyError, ValueError) as exc:
        raise LlmError(f"réponse Anthropic illisible : {exc}") from exc

    return {"model": body.get("model", model), "scores": _clamp(parsed, axes)}


async def embed_openai(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    dimensions: int,
    text: str,
) -> list[float]:
    """L'embedding du dossier, pour la régression interne.

    `dimensions` réduit le vecteur côté OpenAI (Matryoshka) : 256 dimensions
    suffisent largement à une ridge entraînée sur quelques centaines d'œuvres,
    et divisent par six le poids stocké et le nombre de coefficients à estimer.
    """
    response = await http.post(
        f"{OPENAI_BASE}/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": text, "dimensions": dimensions},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise LlmError(f"OpenAI embeddings {response.status_code} : {response.text[:300]}")
    try:
        return response.json()["data"][0]["embedding"]
    except (KeyError, IndexError) as exc:
        raise LlmError(f"réponse embeddings illisible : {exc}") from exc
