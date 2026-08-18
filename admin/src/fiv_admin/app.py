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
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from fiv_admin.config import Settings, get_settings
from fiv_admin.db import build_pool
from fiv_admin.oeuvre import SansPivot
from fiv_admin.queries import SummaryCache
from fiv_admin.routes import acquisition, auth, catalog, training
from fiv_admin.search import Recherche
from fiv_admin.security import LoginThrottle

log = logging.getLogger(__name__)


class VersionedStatic(StaticFiles):
    """Le répertoire statique, avec les en-têtes de cache qui vont avec sa
    façon d'être nommé.

    Le front est construit sous des **noms fixes** — `assets/index.js`,
    `assets/style.css` — et c'est `index.html` qui porte la fraîcheur, sous
    forme de `?version=x.y.z`. Ce choix n'a de sens qu'accompagné de ces deux
    règles, sans quoi il se retourne contre lui-même :

    * **`index.html` : `no-cache`.** Sans en-tête explicite, un navigateur
      applique une heuristique et peut garder la page sans rien redemander. Il
      continuerait alors à réclamer l'ancienne version des fichiers, et un
      déploiement pourrait rester invisible des heures. `no-cache` ne veut pas
      dire « ne garde rien » mais « revalide avant de servir » : avec l'ETag,
      ça coûte un 304 vide.
    * **`assets/*` : cache long.** C'est la contrepartie qu'on achète avec le
      `?version=` — l'URL change à chaque build, donc l'entrée de cache aussi,
      donc rien ne périme jamais sous une URL donnée.
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
        # Aucune vérification de santé ici : ES peut être absent au démarrage
        # (il est facultatif), et c'est le disjoncteur du client qui gère les
        # pannes en cours de route.
        app.state.search = Recherche(settings.es_url, timeout=settings.es_timeout)
        try:
            yield
        finally:
            await app.state.search.fermer()
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

    # Une œuvre sans pivot n'a pas été collectée : c'est un 404, pas un 500.
    # Le message de `SansPivot` dit déjà quoi faire ; le traduire ici évite
    # d'attraper l'exception dans chacune des routes qui touche à la notation.
    @app.exception_handler(SansPivot)
    async def _sans_pivot(request: Request, exc: SansPivot) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(acquisition.router, prefix="/api", tags=["acquisition"])
    app.include_router(catalog.router, prefix="/api", tags=["catalogue"])
    app.include_router(training.router, prefix="/api", tags=["entraînement"])

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
    #
    # Le test porte sur `index.html`, pas sur le répertoire : Docker crée le
    # répertoire hôte d'un volume monté s'il est absent, donc `www/` existe
    # toujours en conteneur, vide ou non. Monter un répertoire vide ferait
    # répondre `{"detail": "Not Found"}` à la racine — un message qui envoie
    # chercher la panne du mauvais côté.
    if settings.has_front:
        app.mount("/", VersionedStatic(directory=settings.web_dist, html=True), name="www")
    else:
        # Le cas normal au premier démarrage : le conteneur tourne, le front
        # n'est pas encore construit.
        log.warning("pas d'index.html dans %s — GET non servi", settings.web_dist)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def missing_front(full_path: str) -> Response:
            return PlainTextResponse(
                f"Rien à servir : pas d'index.html dans {settings.web_dist}.\n\n"
                "Le contenu de www/ est versionné : sur le serveur il arrive par\n"
                "  git pull\n"
                "et se construit sur le poste de dev par\n"
                "  make -C admin web-build\n"
                "\nL'API, elle, répond : /api/health\n",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return app
