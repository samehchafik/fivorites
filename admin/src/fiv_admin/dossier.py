"""Le dossier de notation : `id_tmdb → texte anglais prêt à noter + empreinte`.

C'est l'interface exacte entre l'acquisition et la couche 2. La sélection est
**déterministe** — mêmes données en base, même texte, même sha256 — parce que
l'empreinte de l'entrée fait partie de la provenance de chaque note : sans ça,
impossible de dire si une divergence vient du modèle ou d'un dossier qui a
changé entre deux notations.

La réduction est une sélection, pas un résumé. Résumer par LLM coûterait un
appel de plus et, surtout, aplatirait précisément ce que les axes mesurent —
l'ironie, la forme, l'arrière-goût. On échantillonne les synopsis d'épisodes
sur tout l'arc : huit épisodes répartis portent la tonalité aussi bien que
soixante, pour un cinquième du volume.

Anglais seul, décision du 2026-08-07 : la notation lit l'anglais, les autres
langues collectées servent l'affichage.
"""

from __future__ import annotations

import hashlib
from typing import Any

import psycopg
from psycopg.rows import dict_row

SOURCE = "tmdb"
KIND_SERIES = "tv"
KIND_SEASON = "tv_season"

# Combien de synopsis d'épisodes entrent dans le dossier. Répartis sur tout
# l'arc — début, milieu, fin — parce que le ton d'une série change entre sa
# première et sa dernière saison, et qu'un dossier qui ne lirait que la
# saison 1 noterait une autre œuvre.
EPISODE_SAMPLE = 10

# L'article Wikipédia est la section la plus longue ; au-delà de cette taille,
# on tronque à la dernière phrase complète. Le dossier vise ~2 000 tokens :
# c'est ce qui rend la notation de masse presque gratuite.
WIKIPEDIA_MAX_CHARS = 6000

# Un synopsis de saison résume le ton d'un arc entier — matière précieuse et
# normalement courte ; la troncature n'est là que pour les fiches bavardes.
SEASON_OVERVIEW_MAX_CHARS = 1500

# En dessous, le dossier ne permet pas de noter : la consigne du barème
# autorise le « ne sait pas », mais autant le dire avant de payer l'appel.
MIN_CHARS = 400


def _english_translation(payload: dict[str, Any]) -> dict[str, Any]:
    """L'entrée `en` des traductions — `en-US` d'abord, n'importe quel `en` sinon.

    La fiche est collectée en `fr-FR` : le synopsis anglais ne vit que là.
    """
    entries = (payload.get("translations") or {}).get("translations") or []
    english = [e for e in entries if e.get("iso_639_1") == "en"]
    english.sort(key=lambda e: e.get("iso_3166_1") != "US")
    for entry in english:
        data = entry.get("data") or {}
        if (data.get("overview") or "").strip():
            return data
    return english[0].get("data", {}) if english else {}


def _sample_episodes(seasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un échantillon d'épisodes réparti uniformément sur toute la série.

    Le premier et le dernier épisode utilisables sont toujours pris : c'est
    entre l'ouverture et la conclusion que le ton d'une série se déclare.
    """
    episodes = [
        {
            "season": season_number,
            "episode": ep.get("episode_number"),
            "name": (ep.get("name") or "").strip(),
            "overview": overview,
        }
        for season_number, eps in seasons
        for ep in eps
        if (overview := (ep.get("overview") or "").strip())
    ]
    if len(episodes) <= EPISODE_SAMPLE:
        return episodes

    step = (len(episodes) - 1) / (EPISODE_SAMPLE - 1)
    indexes = sorted({round(i * step) for i in range(EPISODE_SAMPLE)})
    return [episodes[i] for i in indexes]


def _truncate_sentence(text: str, limit: int) -> str:
    """Tronque à la dernière phrase complète avant `limit`.

    Couper au milieu d'un mot produirait un texte différent à chaque réglage de
    limite ; couper à la phrase garde le texte lisible ET l'empreinte stable.
    """
    if len(text) <= limit:
        return text
    cut = text.rfind(". ", 0, limit)
    return text[: cut + 1] if cut > 0 else text[:limit]


async def load_fiche(conn: psycopg.AsyncConnection, id_tmdb: int) -> dict[str, Any] | None:
    """La fiche TMDB la plus récente d'une série — `{"id", "payload"}` — ou
    None si rien de collecté. L'`id` est celui de la ligne de brut : c'est la
    référence de provenance que le journal d'entraînement conserve."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select id, payload from raw_source
            where source = %(source)s and kind = %(kind)s and source_id = %(id)s
              and http_status between 200 and 299 and payload is not null
            order by fetched_at desc limit 1
            """,
            {"source": SOURCE, "kind": KIND_SERIES, "id": str(id_tmdb)},
        )
        return await cur.fetchone()


async def load_seasons(
    conn: psycopg.AsyncConnection, id_tmdb: int
) -> list[tuple[int | None, dict[str, Any]]]:
    """Toutes les saisons en-US (la version la plus récente de chacune),
    triées par numéro. La notation lit l'anglais, donc uniquement en-US."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select distinct on (source_id) source_id, payload
            from raw_source
            where source = %(source)s and kind = %(kind)s and lang = 'en-US'
              and split_part(source_id, '/', 1) = %(id)s
              and http_status between 200 and 299 and payload is not null
            order by source_id, fetched_at desc
            """,
            {"source": SOURCE, "kind": KIND_SEASON, "id": str(id_tmdb)},
        )
        season_rows = await cur.fetchall()
    return sorted(
        ((row["payload"].get("season_number"), row["payload"]) for row in season_rows),
        key=lambda pair: (pair[0] is None, pair[0]),
    )


async def build_dossier(conn: psycopg.AsyncConnection, id_tmdb: int) -> dict[str, Any] | None:
    """Le dossier anglais d'une série, ou None si elle n'est pas collectée."""
    fiche = await load_fiche(conn, id_tmdb)
    if fiche is None:
        return None
    payload = fiche["payload"]
    season_payloads = await load_seasons(conn, id_tmdb)

    async with conn.cursor(row_factory=dict_row) as cur:
        # L'article Wikipédia anglais, si l'enrichissement est passé par là.
        await cur.execute(
            """
            select content from riche_source
            where id_tmdb = %(id)s and source = 'wikipedia' and lang = 'en'
              and content is not null
            """,
            {"id": id_tmdb},
        )
        wiki = await cur.fetchone()

        # Les légendes visuelles, si elles ont été payées (bouton de la page
        # Training 1). L'index porte exactement cet ordre : il est stable, et
        # la stabilité de l'ordre est celle de l'empreinte.
        await cur.execute(
            """
            select label, caption from notation.media_caption
            where id_tmdb = %(id)s order by kind, label, url
            """,
            {"id": id_tmdb},
        )
        captions = await cur.fetchall()

    seasons = [(number, p.get("episodes") or []) for number, p in season_payloads]
    episodes = _sample_episodes(seasons)
    season_overviews = [
        (number, _truncate_sentence(overview, SEASON_OVERVIEW_MAX_CHARS))
        for number, p in season_payloads
        if (overview := (p.get("overview") or "").strip())
    ]
    english = _english_translation(payload)

    title = (english.get("name") or "").strip() or payload.get("original_name") or ""
    overview = (english.get("overview") or "").strip()
    genres = [g.get("name") for g in payload.get("genres") or [] if g.get("name")]
    keywords = [
        k.get("name") for k in (payload.get("keywords") or {}).get("results") or [] if k.get("name")
    ]
    networks = [n.get("name") for n in payload.get("networks") or [] if n.get("name")]
    wikipedia = _truncate_sentence((wiki["content"] if wiki else "").strip(), WIKIPEDIA_MAX_CHARS)

    # L'assemblage. Sections balisées, ordre fixe : le texte EST l'empreinte.
    parts: list[str] = [f"TITLE: {title}"]
    if payload.get("original_name") and payload.get("original_name") != title:
        parts.append(f"ORIGINAL TITLE: {payload['original_name']}")

    facts = [
        f"first aired {payload['first_air_date']}" if payload.get("first_air_date") else None,
        f"country {', '.join(payload.get('origin_country') or [])}"
        if payload.get("origin_country")
        else None,
        f"{payload['number_of_seasons']} seasons" if payload.get("number_of_seasons") else None,
        f"{payload['number_of_episodes']} episodes" if payload.get("number_of_episodes") else None,
        f"network {', '.join(networks)}" if networks else None,
    ]
    parts.append("FACTS: " + "; ".join(f for f in facts if f))

    # Ce que le dossier contient réellement, en clair — factuel, pas une
    # consigne. `MIN_CHARS` ne compte que des caractères : un synopsis seul
    # dépasse le seuil sans qu'aucune section ne porte le ton de l'œuvre dans
    # la durée (synopsis d'épisodes, de saison, Wikipédia). Sans ce signal
    # explicite, un juge peut lire un synopsis de trois phrases et noter avec
    # la même assurance qu'un dossier complet — observé sur des séries au
    # catalogue pauvre (obscures, ou dont la saison en-US n'a jamais été
    # collectée). Le prompt décide comment réagir ; le dossier se contente de
    # dire ce qui est là.
    material = [
        "overview" if overview else "no overview",
        f"{len(season_overviews)} season overview(s)" if season_overviews else None,
        f"{len(episodes)} sampled episode synopses" if episodes else None,
        "Wikipedia article" if wikipedia else None,
        f"{len(captions)} visual caption(s)" if captions else None,
    ]
    parts.append("MATERIAL: " + ", ".join(m for m in material if m) + ".")

    if genres:
        parts.append("GENRES: " + ", ".join(genres))
    if keywords:
        parts.append("KEYWORDS: " + ", ".join(keywords))
    if overview:
        parts.append("OVERVIEW:\n" + overview)
    if season_overviews:
        parts.append(
            "SEASON OVERVIEWS:\n"
            + "\n".join(f"Season {number}: {text}" for number, text in season_overviews)
        )
    if episodes:
        lines = [
            f"S{ep['season']}E{ep['episode']} {ep['name']}: {ep['overview']}" for ep in episodes
        ]
        parts.append("EPISODE SYNOPSES (sampled across the whole run):\n" + "\n".join(lines))
    if captions:
        parts.append(
            "MEDIA (what the official images show, auto-described):\n"
            + "\n".join(f"{row['label']}: {row['caption']}" for row in captions)
        )
    if wikipedia:
        parts.append("WIKIPEDIA (en):\n" + wikipedia)

    text = "\n\n".join(parts)
    return {
        "idTmdb": id_tmdb,
        "rawSourceId": fiche["id"],
        "title": title,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "chars": len(text),
        "enough": len(text) >= MIN_CHARS,
        "sections": {
            "overviewChars": len(overview),
            "seasonOverviews": len(season_overviews),
            "episodeCount": len(episodes),
            "episodeChars": sum(len(ep["overview"]) for ep in episodes),
            "mediaLines": len(captions),
            "wikipediaChars": len(wikipedia),
            "keywords": len(keywords),
        },
    }
