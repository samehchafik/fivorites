"""Les univers observables et ce qu'on sait d'eux aujourd'hui.

Le front propose « séries » et « films » parce que c'est le périmètre annoncé
du projet. Plutôt que de masquer un univers que l'administration ne sait pas
encore afficher, ou de montrer un tableau vide sans explication, l'API répond
explicitement pourquoi, et le front le dit.

⚠️ Depuis le lot 13, `catalog_table=None` sur les films ne veut plus dire « pas
collecté » : la collecte existe, et `sourcing` peut très bien contenir des
centaines de milliers de fiches de films. Ce qui manque est en aval — la
projection de vignettes `admin.movie_card`, pendant de `admin.tv_card`, sans
laquelle la grille n'a rien à lire. Renseigner `catalog_table` avant de l'avoir
créée donnerait une page en erreur, pas une page vide.
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
            "La collecte des films existe depuis le lot 13 "
            "(`tmdb export --univers movies`, puis `tmdb backfill --univers movies`) : "
            "les films collectés sont en base, dans sourcing. "
            "C'est l'administration qui ne sait pas encore les montrer — il lui manque "
            "sa projection de vignettes, `admin.movie_card`, pendant de `admin.tv_card`."
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
