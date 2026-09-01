"""Configuration du site public.

Même base que `sourcing` et `admin` (`fivorites_v2`), et le même principe de
lecture : le service observe le catalogue, il ne le corrige pas. Le seul schéma
dans lequel il écrit est le sien, `visiteur` — la session anonyme et ses
signaux de classement.

Ce service est un SECOND service FastAPI, séparé de l'administration, et la
séparation n'est pas cosmétique : l'admin est verrouillée derrière un login et
explicitement `noindex` ; le site public est fait pour être indexé et servi à
tout le monde. Les mélanger dans un même processus reviendrait à surveiller en
permanence que le catch-all statique de l'un ne recouvre pas les routes de
l'autre.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `parents[2]` remonte de src/fiv_webapp/config.py à la racine du module webapp.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = PROJECT_ROOT / "vendor"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mêmes valeurs par défaut que `sourcing` et `admin` : sur le poste de dev,
    # les trois modules regardent la même base sans rien configurer.
    database_url: str = "postgresql://fivorites_v2@localhost:5432/fivorites_v2"
    sourcing_schema: str = "sourcing"
    admin_schema: str = "admin"
    visiteur_schema: str = "visiteur"

    # Clé de signature du cookie de session anonyme. Vide = un secret éphémère
    # est tiré au démarrage : pratique en dev, inacceptable en production —
    # toutes les sessions (donc tous les classements des visiteurs) sauteraient
    # à chaque redémarrage. `serve` le dit à voix haute.
    secret_key: str = ""
    # Long, exprès : la session anonyme EST le compte du visiteur. Un cookie
    # qui expire en douze heures effacerait ses classements — c'est tout ce
    # qu'il possède chez nous.
    session_ttl_days: int = 180
    session_cookie_name: str = "fiv_session"
    # `Secure` interdit l'envoi du cookie hors HTTPS — faux en dev sur
    # http://localhost, vrai dès qu'il y a un TLS devant.
    cookie_secure: bool = False

    # SMTP, pour le code de vérification d'email. Vide : le code part dans
    # le journal du service — le poste de dev n'envoie pas de vrais mails,
    # et une prod sans SMTP le dit à chaque tentative.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    host: str = "127.0.0.1"
    # 8183 : l'admin occupe 8182, et les deux services tournent côte à côte
    # sur le même poste comme sur le même serveur.
    port: int = 8183

    # En dev, le site est servi par Astro sur 4321 et l'API sur 8183 : deux
    # origines, donc CORS — et `allow_credentials` puisque la session est un
    # cookie. En production le site est servi par l'API elle-même, même
    # origine, et cette liste peut rester vide.
    cors_origins: str = "http://localhost:4321,http://127.0.0.1:4321"

    # La recherche plein texte : le même Elasticsearch que l'admin, les mêmes
    # alias (`catalog-series`, `catalog-movies`, `catalog-livres`). Vide =
    # désactivée — et s'il ne répond pas, la recherche retombe d'elle-même sur
    # son ILIKE : ES accélère, il ne conditionne rien.
    es_url: str = "http://127.0.0.1:9200"
    # Une recherche qui met plus de temps que ça a déjà perdu contre le SQL.
    es_timeout: float = 3.0

    # Le graphe de recommandation : le même Neo4j que l'admin projette
    # (`fiv-admin graphe projeter`). Vide = pas de suggestions — la route
    # répond alors 503 en disant quoi faire, la recherche et la classification
    # ignorent son absence.
    neo4j_url: str = "http://127.0.0.1:7474"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    neo4j_timeout: float = 10.0

    # Le répertoire statique du site public : le build versionné d'Astro
    # (`make -C site build`), servi sous `/` — même convention que `www/` pour
    # l'admin : sur le serveur il arrive par `git pull`, pas de Node là-bas.
    web_dist: Path = PROJECT_ROOT.parent / "www-site"

    migrations_dir: Path = PROJECT_ROOT / "migrations"

    @property
    def has_front(self) -> bool:
        """Y a-t-il quelque chose à servir — pas seulement un répertoire.

        C'est la présence d'`index.html` qui fait foi, pour la même raison que
        côté admin : un volume Docker monté crée le répertoire hôte même vide.
        """
        return (self.web_dist / "index.html").is_file()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
