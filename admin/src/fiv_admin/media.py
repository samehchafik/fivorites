"""Les univers observables et ce qu'on sait d'eux aujourd'hui.

Le front propose « séries » et « films » parce que c'est le périmètre annoncé
du projet. Seules les séries sont collectées à ce stade : il n'existe ni table
d'inventaire ni ligne de brut pour les films. Plutôt que de masquer le second
choix ou d'afficher un tableau vide sans explication, l'API répond
explicitement « cet univers n'est pas encore collecté », et le front le dit.

Le jour où le catalogue des films arrive, il suffit de renseigner
`catalog_table` : le reste du chemin est déjà écrit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Media:
    key: str
    label: str
    # Table d'inventaire dans le schéma `sourcing`. None = univers pas encore
    # collecté.
    catalog_table: str | None
    # `kind` de `raw_source` pour la fiche, et pour ses parties traduites.
    kind: str
    part_kind: str | None
    part_label: str
    # Ce qui est affiché quand l'univers n'a pas de catalogue.
    unavailable_reason: str = ""


MEDIA: dict[str, Media] = {
    "tv": Media(
        key="tv",
        label="Séries",
        catalog_table="tmdb_catalog",
        kind="tv",
        part_kind="tv_season",
        part_label="saisons",
    ),
    "movie": Media(
        key="movie",
        label="Films",
        catalog_table=None,
        kind="movie",
        part_kind=None,
        part_label="",
        unavailable_reason=(
            "La collecte des films n'a pas commencé : ni inventaire "
            "(`sourcing.tmdb_catalog` ne contient que des séries), ni ligne de brut. "
            "Le lot en cours porte sur les séries."
        ),
    ),
}

DEFAULT_MEDIA = "tv"


# Libellés du sélecteur. Les codes sont ceux que la collecte demande à TMDB
# (`TMDB_SEASON_LANGUAGES`), au format BCP-47 région comprise : c'est la région
# qui décide de la variante de traduction renvoyée.
LANGUAGE_LABELS: dict[str, tuple[str, str]] = {
    "fr-FR": ("Français", "🇫🇷"),
    "en-US": ("Anglais", "🇺🇸"),
    "es-ES": ("Espagnol", "🇪🇸"),
    "ar-SA": ("Arabe", "🇸🇦"),
    "tr-TR": ("Turc", "🇹🇷"),
    "pt-BR": ("Portugais", "🇧🇷"),
    "de-DE": ("Allemand", "🇩🇪"),
    "it-IT": ("Italien", "🇮🇹"),
    "ja-JP": ("Japonais", "🇯🇵"),
    "ko-KR": ("Coréen", "🇰🇷"),
    "zh-CN": ("Chinois", "🇨🇳"),
    "ru-RU": ("Russe", "🇷🇺"),
}


def language_label(code: str) -> tuple[str, str]:
    """Libellé et drapeau d'un code langue. Une langue inconnue s'affiche par
    son code plutôt que de disparaître : si elle est en base, elle a été
    collectée, et le tableau doit pouvoir la montrer."""
    return LANGUAGE_LABELS.get(code, (code, "🏳️"))
