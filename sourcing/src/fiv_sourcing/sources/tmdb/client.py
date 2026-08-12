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

# Le pendant film, et la même mise en garde : on la prend une fois, largement,
# avant le grand run. 12 sous-requêtes sur les 20 autorisées.
#
# Écarts avec `SERIES_APPEND`, tous imposés par TMDB :
#   − aggregate_credits — n'existe pas côté film : `credits` est déjà complet,
#                         il n'y a pas de saison 1 dont il ne montrerait que
#                         le casting
#   − episode_groups    — sans objet
#   − content_ratings   — remplacé par `release_dates`, qui porte les
#                         classifications par âge ET les dates de sortie par
#                         pays (salle, numérique, physique)
#   + release_dates     — donc la facette « à voir en famille », comme les
#                         `content_ratings` la donnent aux séries
#
# `lists` reste dehors : la V1 le demandait sans jamais le lire.
#
# Ce qu'un film apporte et qu'une série n'a pas, dans le payload de base et
# sans sous-requête : `runtime`, `tagline`, `budget`, `revenue`,
# `belongs_to_collection` — la saga, que le graphe de recommandation voudra un
# jour — et `imdb_id` au premier niveau, là où une série l'enterre dans
# `external_ids`.
MOVIE_APPEND = (
    "alternative_titles",
    "credits",
    "external_ids",
    "images",
    "keywords",
    "recommendations",
    "release_dates",
    "reviews",
    "similar",
    "translations",
    "videos",
    "watch/providers",
)


class TmdbClient:
    def __init__(self, fetcher: HttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    @property
    def season_languages(self) -> tuple[str, ...]:
        """Langues à demander pour chaque saison.

        Un appel par langue, et c'est le poste de coût dominant de la collecte.
        La raison : `language=` traduit aussi les `overview` de chaque épisode,
        alors que l'endpoint `translations` d'une saison ne porte que sur la
        saison elle-même. Or ce sont les synopsis d'épisode qui constituent la
        matière de notation (§5.1 du doc de sourcing).
        """
        return self._settings.season_languages

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
                    # Même raison pour les vidéos, et le manque était mesurable.
                    # `videos` suit `language` exactement comme les images :
                    # sans cette ligne, on ne récupérait que les bandes-annonces
                    # françaises, qui sont rares. Relevé le 2026-08-11 sur les
                    # 500 séries les plus populaires — celles qui en ont
                    # pratiquement toutes une chez TMDB — seules 155 en
                    # portaient une en base.
                    #
                    # Il n'existe pas d'équivalent pour `reviews` : elles
                    # restent filtrées par `language`, et les récupérer en
                    # anglais demanderait un appel séparé. Mesuré sur les mêmes
                    # 500 séries : 13 en ont. Ça ne vaut pas la requête.
                    "include_video_language": "fr,en,null",
                }
            ),
        )

    async def movie(self, movie_id: int, language: str = "fr-FR") -> FetchResult:
        """La fiche d'un film — un appel, et c'est toute la collecte.

        L'écart de coût avec une série est l'ordre de grandeur du projet : une
        série demande sa fiche plus chaque saison dans chaque langue, soit une
        quarantaine de requêtes pour un feuilleton ordinaire. Un film n'a pas
        de saison, et son synopsis anglais arrive dans `translations`, déjà
        appendu ici. Les 5 000 films les plus populaires se collectent donc en
        5 000 requêtes — quelques minutes au débit courant.
        """
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/movie/{movie_id}",
            self._params(
                {
                    "language": language,
                    "append_to_response": ",".join(MOVIE_APPEND),
                    # Mêmes raisons que pour les séries : les visuels et les
                    # vidéos suivent `language`, et les versions localisées sont
                    # rares. Sans ces deux lignes, on ne récupère que les
                    # affiches et les bandes-annonces françaises.
                    "include_image_language": "fr,en,null",
                    "include_video_language": "fr,en,null",
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
                    "include_video_language": "fr,en,null",
                }
            ),
        )

    async def changes(
        self,
        start_date: str,
        page: int = 1,
        end_date: str | None = None,
        kind: str = "tv",
    ) -> FetchResult:
        """Ids modifiés sur une fenêtre (dates en AAAA-MM-JJ).

        `/tv/changes` ou `/movie/changes` selon le `kind` — deux endpoints de
        forme identique, et c'est le seul point où l'univers entre ici.

        TMDB plafonne la fenêtre à 14 jours ; au-delà, la réponse est
        silencieusement tronquée.
        """
        params: dict[str, Any] = {"start_date": start_date, "page": page}
        if end_date:
            params["end_date"] = end_date
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/{kind}/changes", self._params(params)
        )

    async def configuration(self) -> FetchResult:
        """L'endpoint authentifié le plus léger de TMDB.

        Sert à vérifier les identifiants pour de vrai : une variable non vide ne
        prouve rien, seul TMDB sait si le jeton est valide.
        """
        return await self._fetcher.get_json(
            f"{self._settings.tmdb_base_url}/configuration", self._params({})
        )


def build_public_fetcher(settings: Settings) -> HttpFetcher:
    """Client sans authentification, pour les exports quotidiens.

    Ils sont publics, et on n'envoie pas un jeton à un hôte qui n'en a pas
    besoin — `files.tmdb.org` n'est pas `api.themoviedb.org`.
    """
    return HttpFetcher(
        rate_limit=settings.tmdb_rate_limit,
        timeout=settings.http_timeout,
        max_attempts=settings.http_max_attempts,
        user_agent=settings.http_user_agent,
    )


def build_fetcher(settings: Settings) -> HttpFetcher:
    return HttpFetcher(
        rate_limit=settings.tmdb_rate_limit,
        timeout=settings.http_timeout,
        max_attempts=settings.http_max_attempts,
        user_agent=settings.http_user_agent,
        headers=TmdbClient.auth_headers(settings),
    )
