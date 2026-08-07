"""La sélection des visuels à légender : `brut collecté → liste d'images`.

Les chemins sont déjà dans le brut — l'append_to_response des fiches collecte
`images` (backdrops, affiches), et chaque épisode de saison porte son
`still_path`. Rien à retélécharger : TMDB sert les fichiers en URL publique,
et le modèle de vision lit des URL.

Comme pour le texte du dossier, la sélection est **déterministe** : mêmes
payloads en base, mêmes images, dans le même ordre. Les backdrops sont les
plans larges les plus votés — les plus représentatifs de la photographie de la
série — et les stills d'épisodes sont échantillonnés sur tout l'arc, premier
et dernier compris, pour la même raison que les synopsis : le ton change entre
la première et la dernière saison.
"""

from __future__ import annotations

from typing import Any

# `w780` : assez défini pour lire lumière, ambiance et sujets, assez léger pour
# que le fournisseur le traite en « low detail » — le tarif plancher par image.
IMAGE_BASE = "https://image.tmdb.org/t/p/w780"

BACKDROP_SAMPLE = 6
STILL_SAMPLE = 6


def _evenly(items: list[Any], count: int) -> list[Any]:
    """`count` éléments répartis uniformément, premier et dernier compris."""
    if len(items) <= count:
        return items
    step = (len(items) - 1) / (count - 1)
    indexes = sorted({round(i * step) for i in range(count)})
    return [items[i] for i in indexes]


def select_images(
    fiche: dict[str, Any], seasons: list[tuple[int | None, dict[str, Any]]]
) -> list[dict[str, str]]:
    """Les visuels d'une série : `[{url, kind, label}]`, ordre stable.

    Les labels sont ceux de la section MEDIA du dossier — zéro-paddés pour que
    l'ordre lexicographique (celui de l'index en base) soit l'ordre de
    diffusion.
    """
    backdrops = [
        b
        for b in (fiche.get("images") or {}).get("backdrops") or []
        if (b.get("file_path") or "").strip()
    ]
    # Le vote TMDB comme signal de représentativité, le chemin comme départage :
    # deux backdrops à égalité sortent toujours dans le même ordre.
    backdrops.sort(key=lambda b: (-(b.get("vote_count") or 0), b["file_path"]))

    stills = [
        {"season": number, "episode": ep.get("episode_number"), "path": path}
        for number, payload in seasons
        for ep in payload.get("episodes") or []
        if (path := (ep.get("still_path") or "").strip()) and number is not None
    ]

    images = [
        {
            "url": IMAGE_BASE + b["file_path"],
            "kind": "backdrop",
            "label": f"backdrop {i}",
        }
        for i, b in enumerate(backdrops[:BACKDROP_SAMPLE], start=1)
    ]
    images.extend(
        {
            "url": IMAGE_BASE + s["path"],
            "kind": "still",
            "label": f"S{s['season']:02d}E{s['episode'] or 0:02d}",
        }
        for s in _evenly(stills, STILL_SAMPLE)
    )
    return images
