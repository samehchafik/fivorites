"""Configuration, lue depuis l'environnement ou un fichier `.env` local."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `parents[2]` remonte de src/fiv_sourcing/config.py à la racine du projet. Vrai
# en installation éditable (poste local comme image Docker), faux si le paquet
# était un jour installé en dur dans site-packages — d'où `migrations_dir`,
# surchargeable par l'environnement.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = PROJECT_ROOT / "vendor"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres local de la machine. Une seule base pour tout le projet, un
    # schéma par domaine — la collecte vit dans `sourcing`, les couches métier
    # auront les leurs.
    database_url: str = "postgresql://fivorites_v2@localhost:5432/fivorites_v2"
    db_schema: str = "sourcing"

    # TMDB accepte deux authentifications. Le token v4 est prioritaire s'il est
    # renseigné : il passe en en-tête, donc la clé ne finit pas dans les logs
    # d'URL ni dans `raw_source`.
    tmdb_bearer: str = ""
    tmdb_api_key: str = ""
    tmdb_base_url: str = "https://api.themoviedb.org/3"

    # TMDB a supprimé sa limite dure en 2019 mais applique toujours un plafond
    # implicite. On reste volontairement bas au départ : la valeur se remonte
    # une fois qu'on a mesuré les 429 réellement observés (lot 6).
    tmdb_rate_limit: float = 20.0

    # Langues demandées pour chaque saison — un appel par langue, parce que
    # c'est le seul moyen d'obtenir les synopsis *d'épisode* traduits, qui sont
    # la matière de notation. La fiche de série, elle, ne coûte qu'un appel :
    # `translations` y est déjà dans l'append_to_response.
    #
    # Chaque langue ajoutée multiplie le coût des saisons. Liste en clair,
    # séparée par des virgules, pour qu'on puisse la restreindre par
    # environnement sans toucher au code.
    tmdb_season_languages: str = "fr-FR,en-US,es-ES,ar-SA,tr-TR"

    http_timeout: float = 30.0
    http_max_attempts: int = 5
    http_user_agent: str = "fivorites-sourcing/0.1 (+https://fivorites.com)"

    data_dir: Path = PROJECT_ROOT / "data"
    migrations_dir: Path = PROJECT_ROOT / "migrations"

    @property
    def has_tmdb_credentials(self) -> bool:
        return bool(self.tmdb_bearer or self.tmdb_api_key)

    @property
    def season_languages(self) -> tuple[str, ...]:
        return tuple(code.strip() for code in self.tmdb_season_languages.split(",") if code.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
