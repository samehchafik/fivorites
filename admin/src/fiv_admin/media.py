"""Les univers observables et ce qu'on sait d'eux aujourd'hui.

Le front propose « séries » et « films », et les deux sont désormais servis.
`catalog_table=None` reste le moyen de déclarer un univers annoncé mais pas
encore collecté — `books`, `bd`, `musics` le jour venu : l'API répond alors
explicitement pourquoi plutôt que de rendre un tableau vide qu'on prendrait
pour une collecte à zéro.

Ce qu'un univers doit fournir pour être affichable : une table d'inventaire
(`catalog_table`), la valeur d'univers qui la filtre, et une projection de
vignettes aux colonnes de `admin.tv_card`. Cette dernière contrainte est ce qui
garde une seule requête de grille pour tous les univers — voir
`013_movie_card.sql`, qui traduit `title` en `name` et `release_date` en
`first_air_date` une fois pour toutes.
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
    # La valeur de `tmdb_catalog.univers` et de `oeuvre.univers`. Le même
    # entier y désigne deux œuvres différentes selon l'univers : toute lecture
    # de l'inventaire doit le porter.
    univers: str
    # La projection de vignettes, dans le schéma `admin`. Mêmes colonnes d'une
    # vue à l'autre : c'est ce qui permet à la grille de n'avoir qu'une requête.
    card_view: str
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
        univers="series",
        card_view="tv_card",
        kind="tv",
        part_kind="tv_season",
        part_label="saisons",
    ),
    "movie": Media(
        key="movie",
        label="Films",
        catalog_table="tmdb_catalog",
        univers="movies",
        card_view="movie_card",
        kind="movie",
        # Un film n'a pas de parties : ni saisons, ni épisodes, donc ni
        # accordéon ni couverture par langue à afficher.
        part_kind=None,
        part_label="",
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


def country_of(lang: str) -> str | None:
    """La région d'un code de langue : `fr-FR` → `FR`, `ar-SA` → `SA`.

    TMDB indexe la disponibilité en streaming **par pays**, pas par langue —
    une série est sur Netflix en France et sur Shahid en Arabie saoudite. Le
    sélecteur de langue porte déjà cette région : la réutiliser évite un second
    sélecteur qui dirait presque toujours la même chose que le premier.

    Une langue sans région (`fr` seul) ne désigne aucun marché ; on renvoie None
    plutôt que d'en deviner un.
    """
    region = lang.rpartition("-")[2]
    return region.upper() if len(region) == 2 and region.isalpha() else None


def language_label(code: str) -> tuple[str, str]:
    """Libellé et drapeau d'un code langue. Une langue inconnue s'affiche par
    son code plutôt que de disparaître : si elle est en base, elle a été
    collectée, et le tableau doit pouvoir la montrer."""
    return LANGUAGE_LABELS.get(code, (code, "🏳️"))
