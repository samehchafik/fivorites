"""Le compte : s'inscrire, vérifier son email, se connecter, se déconnecter.

Le fil, tel que la modale du front le déroule :

1. `POST /compte/inscrire` — crée le compte, envoie le code ;
2. `POST /compte/verifier` — le code contre la vérification, et la session
   courante est RATTACHÉE au compte : la personne est connectée dans le même
   geste, et retrouve ses classements d'avant l'inscription ;
3. `POST /compte/connecter` — pour qui a déjà un compte ; non vérifié, la
   réponse le dit et un code repart ;
4. `GET /compte` — qui suis-je (le front le demande avant d'ouvrir les
   fives).

Les réponses d'échec sont volontairement indistinctes (« email ou mot de
passe incorrect », renvoi de code muet sur l'existence de l'adresse) : les
routes publiques ne confirment pas qui est inscrit.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from fiv_webapp.comptes import CompteExiste
from fiv_webapp.deps import (
    CompteOptionnel,
    ComptesDep,
    Conn,
    CourrielDep,
    SessionGarantie,
)

router = APIRouter()


class Inscription(BaseModel):
    pseudo: str = Field(min_length=2, max_length=40)
    email: EmailStr
    mot_de_passe: str = Field(alias="motDePasse", min_length=8, max_length=200)
    genre: str | None = Field(default=None, pattern="^(fille|garcon)$")
    langue: str = "fr"

    model_config = {"populate_by_name": True}


class Verification(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern="^[0-9]{6}$")


class Connexion(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(alias="motDePasse", min_length=1, max_length=200)
    langue: str = "fr"

    model_config = {"populate_by_name": True}


class Renvoi(BaseModel):
    email: EmailStr
    langue: str = "fr"


@router.post("/compte/inscrire")
async def inscrire(
    conn: Conn, comptes: ComptesDep, courriel: CourrielDep, corps: Inscription
) -> dict[str, Any]:
    try:
        compte, code = await comptes.inscrire(
            conn,
            pseudo=corps.pseudo,
            email=str(corps.email),
            mot_de_passe=corps.mot_de_passe,
            genre=corps.genre,
        )
    except CompteExiste:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "un compte existe déjà avec cet email — connectez-vous",
        ) from None
    await courriel.envoyer_code(compte.email, compte.pseudo, code, corps.langue)
    return {"envoye": True, "email": compte.email}


@router.post("/compte/verifier")
async def verifier(
    conn: Conn,
    comptes: ComptesDep,
    session_id: SessionGarantie,
    corps: Verification,
) -> dict[str, Any]:
    compte = await comptes.verifier(conn, email=str(corps.email), code=corps.code)
    if compte is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "code incorrect ou expiré — redemandez-en un",
        )
    # Vérifié = connecté, dans le même geste : la session courante (et tout
    # ce qu'elle a classé) devient celle du compte.
    await comptes.rattacher_session(conn, session_id, compte.id)
    return {"compte": compte.publique()}


@router.post("/compte/connecter")
async def connecter(
    conn: Conn,
    comptes: ComptesDep,
    courriel: CourrielDep,
    session_id: SessionGarantie,
    corps: Connexion,
) -> dict[str, Any]:
    compte = await comptes.connecter(conn, email=str(corps.email), mot_de_passe=corps.mot_de_passe)
    if compte is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "email ou mot de passe incorrect")
    if not compte.verifie:
        # Le compte existe mais l'email n'a jamais été confirmé : on relance
        # le fil de vérification plutôt que de laisser dehors sans issue.
        renvoye = await comptes.renvoyer_code(conn, compte.email)
        if renvoye is not None:
            await courriel.envoyer_code(compte.email, compte.pseudo, renvoye[1], corps.langue)
        return {"verificationRequise": True, "email": compte.email}
    await comptes.rattacher_session(conn, session_id, compte.id)
    return {"compte": compte.publique()}


@router.post("/compte/renvoyer")
async def renvoyer(
    conn: Conn, comptes: ComptesDep, courriel: CourrielDep, corps: Renvoi
) -> dict[str, Any]:
    renvoye = await comptes.renvoyer_code(conn, str(corps.email))
    if renvoye is not None:
        compte, code = renvoye
        await courriel.envoyer_code(compte.email, compte.pseudo, code, corps.langue)
    # La même réponse que l'adresse existe ou non : on ne confirme pas qui
    # est inscrit.
    return {"envoye": True}


@router.post("/compte/deconnecter")
async def deconnecter(
    conn: Conn, comptes: ComptesDep, session_id: SessionGarantie
) -> dict[str, Any]:
    await comptes.detacher_session(conn, session_id)
    return {"deconnecte": True}


@router.get("/compte")
async def compte(compte: CompteOptionnel) -> dict[str, Any]:
    return {"compte": compte.publique() if compte else None}
