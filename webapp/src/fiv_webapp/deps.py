"""Les dépendances des routes : la connexion, la session anonyme, l'univers.

Deux régimes de session, et la différence est tout le contrat du site :

* `SessionOptionnelle` — les lectures. Pas de cookie, pas de session, pas de
  problème : la recherche marche pour tout le monde, les suggestions rendent
  une liste vide qui dit pourquoi.
* `SessionGarantie` — les écritures. Le premier geste de classement CRÉE la
  session et pose le cookie dans la même réponse : le visiteur ne s'inscrit
  pas, il commence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import psycopg
from fastapi import Depends, HTTPException, Request, Response, status

from fiv_webapp.cartes import Cartes
from fiv_webapp.fiche import Fiches
from fiv_webapp.graphe import Graphe
from fiv_webapp.jeton import JetonSession
from fiv_webapp.recherche import Recherche
from fiv_webapp.signaux import Signaux
from fiv_webapp.univers import Univers, univers_ou_400


async def obtenir_conn(request: Request) -> AsyncIterator[psycopg.AsyncConnection]:
    async with request.app.state.pool.connection() as conn:
        yield conn


Conn = Annotated[psycopg.AsyncConnection, Depends(obtenir_conn)]


def obtenir_recherche(request: Request) -> Recherche:
    return request.app.state.recherche


def obtenir_cartes(request: Request) -> Cartes:
    return request.app.state.cartes


def obtenir_fiches(request: Request) -> Fiches:
    return request.app.state.fiches


def obtenir_signaux(request: Request) -> Signaux:
    return request.app.state.signaux


def obtenir_graphe(request: Request) -> Graphe | None:
    return request.app.state.graphe


RechercheDep = Annotated[Recherche, Depends(obtenir_recherche)]
CartesDep = Annotated[Cartes, Depends(obtenir_cartes)]
FichesDep = Annotated[Fiches, Depends(obtenir_fiches)]
SignauxDep = Annotated[Signaux, Depends(obtenir_signaux)]
GrapheOpt = Annotated[Graphe | None, Depends(obtenir_graphe)]


def _jeton(request: Request) -> JetonSession:
    return request.app.state.jeton


def _cookie(request: Request) -> str | None:
    return request.cookies.get(request.app.state.settings.session_cookie_name)


async def session_optionnelle(request: Request, conn: Conn) -> str | None:
    """L'identifiant de session si le cookie est authentique ET que la ligne
    existe encore — sinon None, jamais une erreur : une lecture sans session
    a toujours une réponse honnête."""
    brut = _cookie(request)
    if not brut:
        return None
    session = _jeton(request).lire(brut)
    if session is None:
        return None
    signaux: Signaux = request.app.state.signaux
    if not await signaux.session_existe(conn, session.session_id):
        return None
    return session.session_id


async def session_garantie(request: Request, response: Response, conn: Conn) -> str:
    """La session, créée si nécessaire — et le cookie posé dans la réponse.

    Le cookie est reposé même quand la session existait déjà : c'est ce qui
    fait glisser son expiration au fil de l'usage, plutôt que de déclasser un
    visiteur fidèle au 181e jour.
    """
    signaux: Signaux = request.app.state.signaux
    session_id = await session_optionnelle(request, conn)
    if session_id is None:
        session_id = await signaux.creer_session(conn)

    settings = request.app.state.settings
    response.set_cookie(
        settings.session_cookie_name,
        _jeton(request).emettre(session_id),
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return session_id


SessionOptionnelle = Annotated[str | None, Depends(session_optionnelle)]
SessionGarantie = Annotated[str, Depends(session_garantie)]


def univers_demande(univers: str) -> Univers:
    """Le paramètre `univers` des routes, traduit ou refusé en 400."""
    try:
        return univers_ou_400(univers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


UniversDep = Annotated[Univers, Depends(univers_demande)]
