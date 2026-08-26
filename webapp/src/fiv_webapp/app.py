"""L'application FastAPI du site public : cycle de vie, montage du site.

Deux familles de requêtes, et il n'y en aura pas d'autre :

  /api/public/*  → FastAPI (recherche, signaux, suggestions)
  tout le reste  → un fichier de `www-site/`, le build Astro versionné

Ce service est le pendant public de `fiv_admin.app`, et il partage sa
mécanique — pool ouvert par le lifespan, ES et Neo4j facultatifs et jamais
vérifiés au démarrage, montage statique en dernier. Ce qu'il ne partage PAS :
l'authentification. Ici pas de compte, pas de login — une session anonyme
posée au premier geste de classement, et rien d'autre.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from fiv_webapp.cartes import Cartes
from fiv_webapp.config import Settings, get_settings
from fiv_webapp.db import build_pool
from fiv_webapp.fiche import Fiches
from fiv_webapp.graphe import Graphe
from fiv_webapp.jeton import JetonSession
from fiv_webapp.recherche import Recherche
from fiv_webapp.routes import fiche, personnes, recherche, signaux, suggestions
from fiv_webapp.signaux import Signaux

log = logging.getLogger(__name__)


class VersionedStatic(StaticFiles):
    """Le répertoire statique, avec les en-têtes de cache d'un build Astro.

    Astro nomme ses bundles par empreinte de contenu (`_astro/*.HASH.js`) :
    cache long dessus, l'URL change à chaque build. Les pages HTML, elles,
    gardent leur nom — `no-cache` les fait revalider (un 304 vide avec
    l'ETag), et un déploiement se voit à la requête suivante.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else ""
        response.headers["cache-control"] = (
            "no-cache" if path.endswith(".html") else "public, max-age=31536000"
        )
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    secret = settings.secret_key
    if not secret:
        # Un secret éphémère plutôt qu'un secret par défaut — même règle que
        # partout : une constante dans le dépôt, personne ne la change et
        # n'importe qui forge une session.
        secret = secrets.token_urlsafe(48)
        log.warning(
            "SECRET_KEY absente — secret de session tiré au hasard pour cette "
            "exécution. Les classements des visiteurs ne survivront pas au "
            "redémarrage. Renseigner la variable en production (`openssl rand -hex 32`)."
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = build_pool(
            settings.database_url,
            settings.sourcing_schema,
            settings.admin_schema,
            settings.visiteur_schema,
        )
        await pool.open(wait=True, timeout=10)
        app.state.pool = pool
        # ES et Neo4j : facultatifs, jamais vérifiés au démarrage. La
        # recherche a son disjoncteur et son repli SQL ; les suggestions
        # répondent 503 en disant quoi faire quand le graphe manque.
        app.state.recherche = Recherche(settings.es_url, timeout=settings.es_timeout)
        app.state.graphe = (
            Graphe(
                settings.neo4j_url,
                settings.neo4j_user,
                settings.neo4j_password,
                base=settings.neo4j_database,
                timeout=settings.neo4j_timeout,
            )
            if settings.neo4j_url and settings.neo4j_password
            else None
        )
        try:
            yield
        finally:
            await app.state.recherche.fermer()
            if app.state.graphe is not None:
                await app.state.graphe.fermer()
            await pool.close()

    app = FastAPI(
        title="Fivorites — site public",
        description="Recherche, classification et suggestions — séries, films, livres.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/public/docs",
        openapi_url="/api/public/openapi.json",
    )

    app.state.settings = settings
    app.state.jeton = JetonSession(secret, ttl_seconds=settings.session_ttl_days * 86400)
    app.state.cartes = Cartes()
    app.state.fiches = Fiches()
    app.state.signaux = Signaux()

    # En développement seulement : Astro sert le site sur 4321, l'API répond
    # sur 8183. Deux origines, donc CORS — et `allow_credentials` puisque la
    # session est un cookie. La liste est fermée : jamais `*`.
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type"],
        )

    app.include_router(recherche.router, prefix="/api/public", tags=["recherche"])
    app.include_router(fiche.router, prefix="/api/public", tags=["fiche"])
    app.include_router(personnes.router, prefix="/api/public", tags=["personnes"])
    app.include_router(signaux.router, prefix="/api/public", tags=["signaux"])
    app.include_router(suggestions.router, prefix="/api/public", tags=["suggestions"])

    @app.get("/api/public/health", tags=["service"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Le montage statique, en dernier — monter `/` avant les routeurs
    # recouvrirait `/api`. Une seule origine en production, donc pas de CORS,
    # et le cookie de session reste propriétaire.
    if settings.has_front:
        app.mount("/", VersionedStatic(directory=settings.web_dist, html=True), name="site")
    else:
        log.warning("pas d'index.html dans %s — GET non servi", settings.web_dist)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def missing_front(full_path: str) -> Response:
            return PlainTextResponse(
                f"Rien à servir : pas d'index.html dans {settings.web_dist}.\n\n"
                "Le contenu de www-site/ est versionné : sur le serveur il arrive par\n"
                "  git pull\n"
                "et se construit sur le poste de dev par\n"
                "  make -C site build\n"
                "\nL'API, elle, répond : /api/public/health\n",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return app
