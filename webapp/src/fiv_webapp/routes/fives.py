"""Les fives : les cinq meilleures œuvres, par univers — LE geste du site.

Toutes ces routes exigent un compte vérifié : sans lui, un 401 dont le corps
dit `connexion_requise` — c'est le signal que le front attend pour ouvrir la
modale de compte, puis revenir ici exactement où on en était.

Poser un five pose AUSSI le signal « vu et aimé » : un five est le plus fort
des « j'ai aimé », et il nourrit le moteur par le chemin de tous les autres.
"""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from fiv_webapp.comptes import FIVES_LISTES, FIVES_RANGS, Compte
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


class FiveRequete(BaseModel):
    univers: str
    liste: str = "vie"
    rang: int = Field(ge=1, le=5)
    oeuvre_id: int = Field(alias="oeuvreId", gt=0)

    model_config = {"populate_by_name": True}


def _liste_ou_400(liste: str) -> str:
    if liste not in FIVES_LISTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"liste invalide : {liste} (attendu : {', '.join(FIVES_LISTES)})",
        )
    return liste


@router.get("/fives")
async def lister(
    conn: Conn, comptes: ComptesDep, compte: CompteOptionnel, univers: str, liste: str = "vie"
) -> dict[str, Any]:
    media = univers_ou_400(univers)
    palmares = _liste_ou_400(liste)
    retenu = _connecte(compte)
    return {
        "items": await comptes.fives(conn, retenu.id, media.interne, palmares),
        "rangs": list(FIVES_RANGS),
        "liste": palmares,
    }


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
async def poser(
    conn: Conn,
    comptes: ComptesDep,
    signaux: SignauxDep,
    compte: CompteOptionnel,
    session_id: SessionGarantie,
    corps: FiveRequete,
) -> dict[str, Any]:
    media = univers_ou_400(corps.univers)
    retenu = _connecte(compte)
    await comptes.poser_five(
        conn,
        retenu.id,
        univers_interne=media.interne,
        liste=_liste_ou_400(corps.liste),
        rang=corps.rang,
        oeuvre_id=corps.oeuvre_id,
    )
    # Le five vaut « vu et aimé » — le moteur s'en nourrit immédiatement.
    # `suppress` : le five est posé, le signal est un bonus.
    with contextlib.suppress(Exception):
        await signaux.poser(
            conn,
            session_id,
            oeuvre_id=corps.oeuvre_id,
            univers_interne=media.interne,
            statut="aime",
        )
    return {"pose": True, "rang": corps.rang}


@router.delete("/fives/{univers}/{liste}/{rang}")
async def retirer(
    conn: Conn, comptes: ComptesDep, compte: CompteOptionnel, univers: str, liste: str, rang: int
) -> dict[str, Any]:
    media = univers_ou_400(univers)
    palmares = _liste_ou_400(liste)
    retenu = _connecte(compte)
    if rang not in FIVES_RANGS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rang invalide : {rang}")
    await comptes.retirer_five(
        conn, retenu.id, univers_interne=media.interne, liste=palmares, rang=rang
    )
    return {"retire": True}
