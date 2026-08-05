"""Connexion, déconnexion, session courante.

Il n'y a pas d'inscription : les comptes se créent en ligne de commande
(`fiv-admin user add`). Un front d'administration qui sait fabriquer des
administrateurs n'est plus un front d'administration.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from fiv_admin.deps import Config, Conn, CurrentUser, get_secret, get_throttle
from fiv_admin.security import LoginThrottle, hash_password, issue_session, verify_password

router = APIRouter()

# Haché une fois au chargement, jamais comparé à rien. Il sert à faire durer
# une tentative sur un compte inexistant aussi longtemps qu'une tentative sur
# un compte réel : sans ça, le temps de réponse dit qui existe.
_DUMMY_HASH = hash_password("mot de passe qui ne sert qu'à perdre du temps")


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class Account(BaseModel):
    username: str
    displayName: str | None = None


@router.post("/login", response_model=Account)
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    conn: Conn,
    settings: Config,
    secret: Annotated[str, Depends(get_secret)],
    throttle: Annotated[LoginThrottle, Depends(get_throttle)],
) -> Account:
    address = request.client.host if request.client else "?"

    wait = throttle.locked_for(body.username, address)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"trop de tentatives — réessayer dans {wait} s",
            headers={"Retry-After": str(wait)},
        )

    async with conn.cursor() as cur:
        await cur.execute(
            "select username, password_hash, display_name, disabled"
            " from admin_user where username = %s",
            (body.username,),
        )
        row = await cur.fetchone()

    # Un compte inconnu et un mot de passe faux donnent la même réponse et le
    # même temps de calcul.
    stored_hash = row[1] if row else _DUMMY_HASH
    valid = verify_password(body.password, stored_hash)

    if row is None or not valid or row[3]:
        throttle.record_failure(body.username, address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "identifiants invalides")

    throttle.reset(body.username, address)
    async with conn.cursor() as cur:
        await cur.execute(
            "update admin_user set last_login_at = now() where username = %s", (row[0],)
        )

    token = issue_session(row[0], secret, ttl_seconds=settings.session_ttl_hours * 3600)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        # HttpOnly : le jeton n'est pas lisible en JavaScript, donc pas
        # exfiltrable par une injection dans le front.
        httponly=True,
        # Strict : le cookie n'accompagne aucune requête venue d'un autre site,
        # ce qui referme la falsification de requête inter-site sans jeton CSRF
        # séparé. L'administration n'a aucun lien entrant à préserver.
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )
    return Account(username=row[0], displayName=row[2])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: Config) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
    )


@router.get("/me", response_model=Account)
async def me(user: CurrentUser, conn: Conn) -> Account:
    async with conn.cursor() as cur:
        await cur.execute(
            "select username, display_name from admin_user where username = %s", (user,)
        )
        row = await cur.fetchone()
    if row is None:  # pragma: no cover — `current_user` l'a déjà vérifié
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "compte inconnu")
    return Account(username=row[0], displayName=row[1])
