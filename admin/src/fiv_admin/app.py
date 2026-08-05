"""L'application FastAPI : cycle de vie, sécurité de transport, montage du front.

Trois familles de routes, et le découpage suit ce qu'elles touchent :

* `/api/auth/*` — les comptes (la seule écriture métier : l'horodatage de
  connexion) ;
* `/api/acquisition/*` — l'avancement, en lecture pure sur `sourcing` ;
* `/api/catalog/*` — la navigation dans ce qui a été collecté ; écrit
  uniquement la projection d'affichage, sur demande explicite.

Rien dans ce service ne déclenche de collecte. Le front observe le pipeline,
il ne le pilote pas : l'acquisition est un traitement par lots qui se lance en
ligne de commande, et lui donner un bouton depuis une page web reviendrait à
pouvoir engager deux millions de requêtes TMDB d'un clic.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from fiv_admin.config import Settings, get_settings
from fiv_admin.db import build_pool
from fiv_admin.queries import SummaryCache
from fiv_admin.routes import acquisition, auth, catalog
from fiv_admin.security import LoginThrottle

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    secret = settings.admin_secret_key
    if not secret:
        # Un secret éphémère plutôt qu'un secret par défaut : une constante
        # écrite dans le dépôt serait le pire des deux mondes — ça marche, donc
        # personne ne la change, et n'importe qui peut forger une session.
        secret = secrets.token_urlsafe(48)
        log.warning(
            "ADMIN_SECRET_KEY absente — secret de session tiré au hasard pour cette "
            "exécution. Les sessions ne survivront pas au redémarrage. "
            "Renseigner la variable en production (`openssl rand -hex 32`)."
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = build_pool(
            settings.database_url,
            settings.sourcing_schema,
            settings.admin_schema,
        )
        await pool.open(wait=True, timeout=10)
        app.state.pool = pool
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(
        title="Fivorites — administration",
        description="Suivi de l'acquisition, par univers et par langue.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.state.settings = settings
    app.state.secret = secret
    app.state.throttle = LoginThrottle(settings.login_max_attempts, settings.login_lockout_seconds)
    app.state.summary_cache = SummaryCache(settings.summary_cache_seconds)

    # En développement seulement : Vite sert le front sur 5173, l'API répond sur
    # 8182. Deux origines, donc CORS — et `allow_credentials` puisque la session
    # est un cookie. La liste est fermée : jamais `*`, qui est de toute façon
    # incompatible avec les cookies.
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(acquisition.router, prefix="/api", tags=["acquisition"])
    app.include_router(catalog.router, prefix="/api", tags=["catalogue"])

    @app.get("/api/health", tags=["service"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Le partage des requêtes, et il n'y en a que deux sortes :
    #
    #   /api/*        → FastAPI (les appels du front)
    #   tout le reste → un fichier de `www/`, le répertoire statique
    #
    # Le montage est fait **en dernier** : monter `/` avant les routeurs
    # recouvrirait `/api`. Une seule origine, donc pas de CORS en production, et
    # le cookie de session reste propriétaire.
    #
    # `www/` ne contient que le résultat du build — les sources React sont dans
    # `front/` et n'y descendent jamais. C'est un volume monté depuis l'hôte,
    # pas un contenu d'image : redéployer le front ne demande pas de
    # reconstruire l'image.
    if settings.web_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="www")
    else:
        # Le cas normal au premier démarrage : le conteneur tourne, le front
        # n'est pas encore construit. Un 404 nu enverrait chercher la panne du
        # mauvais côté ; on dit ce qui manque et comment le produire.
        log.warning("répertoire statique absent de %s — GET non servi", settings.web_dist)

        @app.get("/", include_in_schema=False)
        async def missing_front() -> Response:
            return PlainTextResponse(
                f"Le répertoire statique est absent : {settings.web_dist}.\n"
                "Il se remplit depuis les sources de front/.\n\n"
                "Sur le serveur :  docker compose run --rm www-build\n"
                "En local      :  make -C admin web-build\n"
                "\nL'API, elle, répond : /api/health\n",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return app
