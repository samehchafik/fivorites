"""Dépendances partagées : la connexion, la configuration, le compte connecté."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import psycopg
from fastapi import Depends, HTTPException, Request, status

from fiv_admin.config import Settings
from fiv_admin.queries import SummaryCache
from fiv_admin.security import LoginThrottle, read_session


def get_config(request: Request) -> Settings:
    return request.app.state.settings


def get_secret(request: Request) -> str:
    return request.app.state.secret


def get_throttle(request: Request) -> LoginThrottle:
    return request.app.state.throttle


def get_summary_cache(request: Request) -> SummaryCache:
    return request.app.state.summary_cache


async def get_conn(request: Request) -> AsyncIterator[psycopg.AsyncConnection]:
    async with request.app.state.pool.connection() as conn:
        yield conn


async def current_user(
    request: Request,
    conn: Annotated[psycopg.AsyncConnection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_config)],
    secret: Annotated[str, Depends(get_secret)],
) -> str:
    """Le compte de la session, ou 401.

    Le cookie prouve seulement qu'une session a été signée par ce service. On
    revérifie le compte à chaque requête : désactiver quelqu'un doit avoir un
    effet immédiat, pas au bout des douze heures du jeton.
    """
    token = request.cookies.get(settings.session_cookie_name)
    session = read_session(token, secret) if token else None
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session absente ou expirée")

    async with conn.cursor() as cur:
        await cur.execute(
            "select disabled from admin_user where username = %s", (session.username,)
        )
        row = await cur.fetchone()
    if row is None or row[0]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "compte inconnu ou désactivé")
    return session.username


CurrentUser = Annotated[str, Depends(current_user)]
Conn = Annotated[psycopg.AsyncConnection, Depends(get_conn)]
Config = Annotated[Settings, Depends(get_config)]
