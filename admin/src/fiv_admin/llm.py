"""Les juges : OpenAI (le noteur), Anthropic Haiku (le contre-juge).

Deux familles de modèles, exprès. Les notes de masse descendent d'OpenAI, et
les poids internes s'apprennent dessus : un juge d'une autre famille est le
seul à pouvoir détecter un biais que toute la lignée partagerait. Haiku ne
note pas la masse — il contredit, ou pas.

Ce module ne contient que des appels payants. L'encodage de **production** est
local (`embed.py`) : la traîne du catalogue ne doit dépendre d'aucune API.
`embed_openai` n'est pas une exception à cette règle — c'est un candidat de
comparaison, jamais un chemin de production, et `comparer_encodeurs` est seul à
l'appeler.

Pourquoi un encodeur d'API malgré la règle : les quatre candidats locaux sont
tous de petits modèles de similarité sémantique, et ils s'équivalent à 0,006
près — ce qui dit qu'ils sont interchangeables entre eux, pas qu'un encodeur
plus savant ne ferait pas mieux. Le voisinage de Lucifer a rendu la question
concrète : ses dix plus proches sont des policiers sombres, l'encodeur retient
le sujet et jette le ton, alors que le titre de la série est dans le dossier.
Un modèle qui sait ce que « Lucifer » désigne la rangerait ailleurs sur le même
texte. Cette hypothèse-là se mesure pour vingt centimes ; la refuser par
principe coûterait plus cher que de la tester.

La sortie est **contrainte** au schéma dans les deux cas : six entiers et six
confiances, jamais de prose à reparser. Les bornes 1-10 sont vérifiées ici (les
sorties structurées d'Anthropic ne portent pas de contraintes numériques), et
un score hors bornes est ramené dedans plutôt que rejeté — un 0 ou un 11 est
une maladresse d'échelle, pas une absence de jugement.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

OPENAI_BASE = "https://api.openai.com/v1"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"

# Assez pour un dossier de ~2 000 tokens et une réponse de ~300 : un appel qui
# dépasse ça est un appel parti en vrille, pas un appel lent.
TIMEOUT = httpx.Timeout(90.0, connect=10.0)

# Le tarif public des encodeurs OpenAI au 2026-08-11, en dollars par million de
# tokens. Sert à annoncer la dépense AVANT d'appeler : une comparaison dont on
# découvre le coût sur la facture ne se relance jamais.
TARIF_EMBEDDING = {
    "text-embedding-3-large": 0.13,
    "text-embedding-3-small": 0.02,
}

# Assez de dossiers par requête pour que la latence réseau ne domine pas, assez
# peu pour rester loin des 300 000 tokens acceptés par appel : à douze mille
# caractères, cinquante dossiers font environ 150 000 tokens.
LOT_EMBEDDING = 50


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


# La consigne de légende. En anglais, comme tout le dossier ; factuelle,
# tournée vers ce que les axes visuels mesurent — lumière, couleur, ambiance —
# et fermée à la spéculation narrative : le modèle décrit, il ne raconte pas.
CAPTION_PROMPT = (
    "You will receive official images from one television series: wide backdrops "
    "and episode stills. For EACH image, write one short English line (under 25 "
    "words) describing only what is visible: lighting (dark, bright, neon...), "
    "dominant colours, setting, mood, notable subjects. Be factual. No plot "
    "speculation, no character names, no episode guesses."
)


def captions_schema(count: int) -> dict[str, Any]:
    """Une propriété par image (`image_1`…`image_n`), toutes requises : le
    schéma strict garantit exactement une légende par visuel envoyé — pas de
    tableau à recompter."""
    keys = [f"image_{i}" for i in range(1, count + 1)]
    return {
        "type": "object",
        "properties": {key: {"type": "string"} for key in keys},
        "required": keys,
        "additionalProperties": False,
    }


async def caption_openai(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    images: list[dict[str, str]],
) -> dict[str, Any]:
    """Les légendes d'une liste d'images `[{url, kind, label}]`, en un appel.

    Un seul appel pour tout le lot : la consigne n'est payée qu'une fois, et
    `detail: low` ramène chaque image à son tarif plancher — largement assez
    pour lire une lumière et une ambiance.
    """
    content: list[dict[str, Any]] = []
    for i, image in enumerate(images, start=1):
        content.append({"type": "text", "text": f"Image {i} ({image['kind']} {image['label']}):"})
        content.append({"type": "image_url", "image_url": {"url": image["url"], "detail": "low"}})

    response = await http.post(
        f"{OPENAI_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": CAPTION_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "image_captions",
                    "strict": True,
                    "schema": captions_schema(len(images)),
                },
            },
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise LlmError(f"OpenAI vision {response.status_code} : {response.text[:300]}")

    body = response.json()
    try:
        import json

        parsed = json.loads(body["choices"][0]["message"]["content"])
        captions = [str(parsed[f"image_{i}"]).strip() for i in range(1, len(images) + 1)]
    except (KeyError, IndexError, ValueError) as exc:
        raise LlmError(f"réponse vision illisible : {exc}") from exc

    return {"model": body.get("model", model), "captions": captions}


async def embed_openai(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    textes: list[str],
    dimensions: int | None = None,
) -> list[list[float]]:
    """Les vecteurs d'une liste de dossiers, par l'API OpenAI.

    Candidat de comparaison uniquement : `comparer_encodeurs` est seul appelant,
    et rien de ce qui sort d'ici n'atteint `notation.embedding`. Mélanger deux
    espaces vectoriels dans la table qui sert la production coûterait bien plus
    qu'une comparaison ratée.

    `dimensions` exploite le rétrécissement natif de la famille
    `text-embedding-3` : le même modèle rend un vecteur plus court sans être
    réencodé. C'est ce qui permet de séparer deux causes qu'on confondrait
    sinon — un candidat qui gagne avec 3 072 dimensions contre les 512 de jina
    gagne peut-être seulement parce qu'il en a six fois plus, sur un corpus qui
    n'a que 502 exemples. Le comparer aussi à 512 tranche.

    Les lots sont séquentiels, pas concurrents : cinq cents dossiers font dix
    appels, la durée totale est de quelques secondes, et un parallélisme ne
    ferait gagner que du 429.
    """
    vecteurs: list[list[float]] = []
    for depart in range(0, len(textes), LOT_EMBEDDING):
        lot = textes[depart : depart + LOT_EMBEDDING]
        charge: dict[str, Any] = {"model": model, "input": lot}
        if dimensions:
            charge["dimensions"] = dimensions

        # Reprise sur 429 et sur les 5xx : un encodage de cinq cents dossiers
        # qui échoue au neuvième lot aurait déjà été payé pour rien.
        derniere: str = ""
        for essai in range(4):
            response = await http.post(
                f"{OPENAI_BASE}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json=charge,
                timeout=TIMEOUT,
            )
            if response.status_code == 200:
                break
            derniere = f"OpenAI {response.status_code} : {response.text[:300]}"
            if response.status_code != 429 and response.status_code < 500:
                raise LlmError(derniere)
            await asyncio.sleep(2.0 * (essai + 1))
        else:
            raise LlmError(f"encodage abandonné après quatre essais — {derniere}")

        body = response.json()
        try:
            # L'API ne garantit pas l'ordre de `data` ; `index` si. Se fier au
            # rang de la liste rendrait des vecteurs appariés aux mauvaises
            # œuvres, et une régression sur des paires mélangées ne ressemble
            # pas à une erreur — elle ressemble à un mauvais encodeur.
            lot_vecteurs = sorted(body["data"], key=lambda d: int(d["index"]))
            vecteurs.extend([float(v) for v in d["embedding"]] for d in lot_vecteurs)
        except (KeyError, TypeError, ValueError) as exc:
            raise LlmError(f"réponse d'encodage illisible : {exc}") from exc

    if len(vecteurs) != len(textes):
        raise LlmError(f"{len(vecteurs)} vecteurs rendus pour {len(textes)} dossiers")
    return vecteurs
