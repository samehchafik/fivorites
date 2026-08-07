"""Configuration du front d'administration.

Même base que `sourcing` (`fivorites_v2`), mais un accès en **lecture seule**
sur ses tables : l'administration observe la collecte, elle ne la corrige pas.
Le seul schéma dans lequel elle écrit est le sien, `admin`, et uniquement pour
les comptes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `parents[2]` remonte de src/fiv_admin/config.py à la racine du module admin.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = PROJECT_ROOT / "vendor"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mêmes valeurs par défaut que `sourcing` : sur le poste de dev, les deux
    # modules regardent la même base sans qu'on ait rien à configurer.
    database_url: str = "postgresql://fivorites_v2@localhost:5432/fivorites_v2"
    sourcing_schema: str = "sourcing"
    admin_schema: str = "admin"

    # Clé de signature des sessions. Vide = un secret éphémère est tiré au
    # démarrage : pratique en dev (rien à configurer), inacceptable en
    # production (toute session saute à chaque redémarrage, et deux instances
    # ne se reconnaissent pas). `serve` le dit à voix haute.
    admin_secret_key: str = ""
    session_ttl_hours: int = 12
    session_cookie_name: str = "fiv_admin_session"
    # `Secure` interdit l'envoi du cookie hors HTTPS — donc à laisser à faux en
    # dev sur http://localhost, et à mettre à vrai dès qu'il y a un TLS devant.
    cookie_secure: bool = False

    host: str = "127.0.0.1"
    port: int = 8182

    # En dev, le front est servi par Vite sur 5173 et l'API sur 8182 : deux
    # origines, donc CORS avec `credentials`. En production le front est servi
    # par l'API elle-même, même origine, et cette liste peut rester vide.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Les langues proposées par le sélecteur. Même liste que
    # `TMDB_SEASON_LANGUAGES` côté sourcing — c'est elle qui décide de ce qui
    # est collecté, donc de ce qu'il y a à afficher. Les langues réellement
    # présentes en base s'y ajoutent d'elles-mêmes.
    season_languages: str = "fr-FR,en-US,es-ES,ar-SA,tr-TR"

    # Le répertoire statique : tout ce qui n'est pas `/api/*` y est cherché.
    #
    # Il ne contient que le résultat du build — `index.html` et ses fichiers.
    # Les sources React sont dans `front/`, et n'y descendent jamais : un
    # répertoire servi en HTTP n'a à contenir ni code source ni node_modules.
    #
    # En conteneur il est monté depuis l'hôte, donc redéployer le front ne
    # demande pas de reconstruire l'image — d'où la surcharge par variable
    # d'environnement.
    web_dist: Path = PROJECT_ROOT.parent / "www"

    migrations_dir: Path = PROJECT_ROOT / "migrations"

    # Freinage des tentatives de connexion, par couple (compte, adresse).
    login_max_attempts: int = 5
    login_lockout_seconds: int = 300

    # L'entraînement de la notation (pages Training 1 et 2). Deux familles de
    # modèles, exprès : OpenAI note, Haiku contredit — un contre-juge d'une
    # autre lignée est le seul à voir un biais que toute la chaîne partagerait.
    # Les identifiants de modèles sont des réglages : ils périment plus vite
    # que le code.
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    anthropic_model: str = "claude-haiku-4-5"
    openai_embed_model: str = "text-embedding-3-small"
    # 256 dimensions (réduction Matryoshka côté OpenAI) : largement assez pour
    # une ridge sur quelques centaines d'œuvres, six fois moins de coefficients.
    embed_dimensions: int = 256

    # Les compteurs d'en-tête agrègent `raw_source` en entier. À l'échelle du
    # catalogue complet ça se compte en secondes : on les garde en mémoire un
    # court instant plutôt que de les recalculer à chaque affichage.
    summary_cache_seconds: int = 60

    @property
    def has_front(self) -> bool:
        """Y a-t-il quelque chose à servir — pas seulement un répertoire.

        La distinction n'est pas byzantine : en conteneur, `www/` est un volume
        monté, et Docker **crée le répertoire hôte s'il est absent**. Un
        `web_dist.is_dir()` répond donc oui sur un front qui n'a jamais été
        construit, et la première requête tombe sur un `{"detail":"Not Found"}`
        qui n'apprend rien à personne. C'est la présence d'`index.html` qui fait
        foi.
        """
        return (self.web_dist / "index.html").is_file()

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(code.strip() for code in self.season_languages.split(",") if code.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
