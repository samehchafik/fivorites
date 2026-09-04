"""Les palmarès : des TOP 5 en nombre libre — dont UN est « de ma vie ».

Toutes les écritures exigent un compte vérifié : sans lui, un 401 dont le
corps dit `connexion_requise` — c'est le signal que le front attend pour
ouvrir la modale de compte, puis revenir ici exactement où on en était.
La vitrine de la communauté, elle, est publique.

Poser une œuvre dans un palmarès pose AUSSI le signal « vu et aimé » : un
five est le plus fort des « j'ai aimé », et il nourrit le moteur par le
chemin de tous les autres.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from fiv_webapp.comptes import Compte
from fiv_webapp.deps import CompteOptionnel, ComptesDep, Conn, SessionGarantie, SignauxDep
from fiv_webapp.univers import univers_ou_400

router = APIRouter()


def _connecte(compte: Compte | None) -> Compte:
    if compte is None or not compte.verifie:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"raison": "connexion_requise"},
        )
    return compte


def _introuvable() -> HTTPException:
    # Un palmarès d'autrui et un palmarès inexistant se répondent pareil :
    # ne pas confirmer ce qui existe chez les autres.
    return HTTPException(status.HTTP_404_NOT_FOUND, "palmarès introuvable")


class Creation(BaseModel):
    univers: str
    titre: str | None = Field(default=None, min_length=1, max_length=80)


class Retouche(BaseModel):
    """Renommer, couronner ou décoronner. `titre: ""` efface le nom (retour
    au générique) ; `vie: true` en fait « le TOP 5 de ma vie » (l'ancien est
    décoronné), `vie: false` rend le palmarès ordinaire — aucun couronné est
    un état permis."""

    titre: str | None = Field(default=None, max_length=80)
    vie: bool | None = None


class Position(BaseModel):
    rang: int = Field(ge=1, le=5)
    oeuvre_id: int = Field(alias="oeuvreId", gt=0)

    model_config = {"populate_by_name": True}


@router.get("/fives")
async def lister(
    conn: Conn, comptes: ComptesDep, compte: CompteOptionnel, univers: str
) -> dict[str, Any]:
    media = univers_ou_400(univers)
    retenu = _connecte(compte)
    return {"items": await comptes.palmares(conn, retenu.id, media.interne)}


@router.get("/fives/communaute")
async def communaute(
    conn: Conn, comptes: ComptesDep, univers: str, limite: int = 4
) -> dict[str, Any]:
    """Des fives de la communauté V1, tirés au sort — publics, anonymes
    (les membres importés sont masqués), et sans compte requis : c'est une
    vitrine, pas un espace personnel."""
    media = univers_ou_400(univers)
    return {"items": await comptes.fives_communaute(conn, media.interne, limite=min(limite, 10))}


@router.post("/fives")
async def creer(
    conn: Conn, comptes: ComptesDep, compte: CompteOptionnel, corps: Creation
) -> dict[str, Any]:
    media = univers_ou_400(corps.univers)
    retenu = _connecte(compte)
    palmares = await comptes.creer_palmares(
        conn, retenu.id, univers_interne=media.interne, titre=corps.titre
    )
    return {"palmares": palmares}


@router.patch("/fives/{palmares_id}")
async def retoucher(
    conn: Conn,
    comptes: ComptesDep,
    compte: CompteOptionnel,
    palmares_id: UUID,
    corps: Retouche,
) -> dict[str, Any]:
    retenu = _connecte(compte)
    if corps.titre is not None:
        titre = corps.titre.strip() or None
        if not await comptes.renommer_palmares(conn, retenu.id, str(palmares_id), titre):
            raise _introuvable()
    if corps.vie is not None and not await comptes.definir_vie(
        conn, retenu.id, str(palmares_id), corps.vie
    ):
        raise _introuvable()
    return {"retouche": True}


@router.delete("/fives/{palmares_id}")
async def supprimer(
    conn: Conn, comptes: ComptesDep, compte: CompteOptionnel, palmares_id: UUID
) -> dict[str, Any]:
    retenu = _connecte(compte)
    if not await comptes.supprimer_palmares(conn, retenu.id, str(palmares_id)):
        raise _introuvable()
    return {"supprime": True}


@router.post("/fives/{palmares_id}/positions")
async def poser(
    conn: Conn,
    comptes: ComptesDep,
    signaux: SignauxDep,
    compte: CompteOptionnel,
    session_id: SessionGarantie,
    palmares_id: UUID,
    corps: Position,
) -> dict[str, Any]:
    retenu = _connecte(compte)
    univers_interne = await comptes.poser_position(
        conn, retenu.id, str(palmares_id), rang=corps.rang, oeuvre_id=corps.oeuvre_id
    )
    if univers_interne is None:
        raise _introuvable()
    # Le five vaut « vu et aimé » — le moteur s'en nourrit immédiatement.
    # `suppress` : le five est posé, le signal est un bonus.
    with contextlib.suppress(Exception):
        await signaux.poser(
            conn,
            session_id,
            oeuvre_id=corps.oeuvre_id,
            univers_interne=univers_interne,
            statut="aime",
        )
    return {"pose": True, "rang": corps.rang}


@router.delete("/fives/{palmares_id}/positions/{rang}")
async def retirer(
    conn: Conn, comptes: ComptesDep, compte: CompteOptionnel, palmares_id: UUID, rang: int
) -> dict[str, Any]:
    retenu = _connecte(compte)
    if rang < 1 or rang > 5:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rang invalide : {rang}")
    if not await comptes.retirer_position(conn, retenu.id, str(palmares_id), rang):
        raise _introuvable()
    return {"retire": True}
