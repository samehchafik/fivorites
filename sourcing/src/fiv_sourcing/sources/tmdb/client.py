"""Client TMDB.

Le point sensible de ce fichier est `SERIES_APPEND`. Le brut protège des
changements de *dérivation*, pas des changements de *collecte* : le jour où on
ajoute un sous-appel à cette liste, il faut retélécharger le catalogue entier.
C'est donc la seule décision de ce projet qu'on prend une fois, largement, avant
le grand run — pas le mapping.
"""

from __future__ import annotations

from typing import Any

from fiv_sourcing.config import Settings
from fiv_sourcing.http import FetchResult, HttpFetcher

# `append_to_response` accepte 20 sous-requêtes ; on en utilise 15.
#
# Écarts assumés avec la V1 :
#   + external_ids     — imdb_id / tvdb_id / wikidata_id, les clés de jointure
#                        vers Wikidata et Wikipédia. Sans elles, rien de la
#                        couche géographique n'est possible.
#   + content_ratings  — classification par âge (facette « à voir en famille »)
#   + watch/providers  — disponibilité par plateforme et par pays (JustWatch)
#   + aggregate_credits— crédits consolidés sur toute la série, là où `credits`
#                        ne renvoie que le casting de la saison 1
#   - releases, lists  — endpoints *films*. La V1 les demandait sur des séries
#                        depuis 2017 : deux sous-requêtes pour rien.
SERIES_APPEND = (
    "aggregate_credits",
    "alternative_titles",
    "content_ratings",
    "credits",
    "episode_groups",
    "external_ids",
    "images",
    "keywords",
    "recommendations",
    "reviews",
    "similar",
    "translations",
    "videos",
    "watch/providers",
)

SEASON_APPEND = ("credits", "external_ids", "images", "videos")

# Deux langues par saison, comme en V1 : c'est l'appariement titre+synopsis
# d'épisode en fr et en qui constitue la matière de notation (§5.1 du doc).
SEASON_LANGUAGES = ("fr-FR", "en-US")


class TmdbClient:
    def __init__(self, fetcher: HttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    @staticmethod
    def auth_headers(settings: Settings) -> dict[str, str]:
        """Le token v4 passe en en-tête : la clé ne finit ni dans les logs
        d'URL, ni dans `raw_source`."""
        if settings.tmdb_bearer:
            return {"Authorization": f"Bearer {settings.tmdb_bearer}"}
        return {}

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = dict(extra)
        if not self._settings.tmdb_bearer and self._settings.tmdb_api_key:
            params["api_key"] = self._settings.tmdb_api_key
        return params

    async def series(self, tv_id: int, language: str = "fr-FR") -> FetchResult:
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/tv/{tv_id}",
            self._params(
                {
                    "language": language,
                    "append_to_response": ",".join(SERIES_APPEND),
                    # Les affiches localisées sont rarement complètes ; `null`
                    # récupère les visuels sans texte, utilisables partout.
                    "include_image_language": "fr,en,null",
                }
            ),
        )

    async def season(self, tv_id: int, season_number: int, language: str = "fr-FR") -> FetchResult:
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/tv/{tv_id}/season/{season_number}",
            self._params(
                {
                    "language": language,
                    "append_to_response": ",".join(SEASON_APPEND),
                }
            ),
        )

    async def changes(self, start_date: str, page: int = 1) -> FetchResult:
        """Ids de séries modifiées depuis `start_date` (AAAA-MM-JJ)."""
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/tv/changes",
            self._params({"start_date": start_date, "page": page}),
        )

    async def configuration(self) -> FetchResult:
        """L'endpoint authentifié le plus léger de TMDB.

        Sert à vérifier les identifiants pour de vrai : une variable non vide ne
        prouve rien, seul TMDB sait si le jeton est valide.
        """
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/configuration", self._params({})
        )


def build_fetcher(settings: Settings) -> HttpFetcher:
    return HttpFetcher(
        rate_limit=settings.tmdb_rate_limit,
        timeout=settings.http_timeout,
        max_attempts=settings.http_max_attempts,
        user_agent=settings.http_user_agent,
        headers=TmdbClient.auth_headers(settings),
    )
