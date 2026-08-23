"""Les gestes de classement : poser, relire, retirer.

C'est la seule famille de routes qui écrit, et elle n'écrit que dans
`visiteur` — le catalogue reste intouchable depuis le site, comme depuis
l'admin.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from psycopg.errors import ForeignKeyViolation
from pydantic import BaseModel, Field

from fiv_webapp.deps import Conn, SessionGarantie, SessionOptionnelle, SignauxDep, univers_demande
from fiv_webapp.signaux import STATUTS

router = APIRouter()


class SignalRequete(BaseModel):
    """Le corps d'un geste : quelle œuvre (le pivot), quel univers, quel
    statut. Le front envoie du camelCase, le serveur vit en snake_case —
    l'alias fait le pont."""

    oeuvre_id: int = Field(alias="oeuvreId", gt=0)
    univers: str
    statut: str

    model_config = {"populate_by_name": True}


@router.post("/signaux")
async def poser(
    conn: Conn, signaux: SignauxDep, session_id: SessionGarantie, geste: SignalRequete
) -> dict[str, Any]:
    if geste.statut not in STATUTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"statut inconnu : {geste.statut} (attendu : {', '.join(STATUTS)})",
        )
    univers = univers_demande(geste.univers)
    try:
        await signaux.poser(
            conn,
            session_id,
            oeuvre_id=geste.oeuvre_id,
            univers_interne=univers.interne,
            statut=geste.statut,
        )
    except ForeignKeyViolation as exc:
        # La clé étrangère sur `sourcing.oeuvre` : un pivot inventé (ou une
        # œuvre purgée entre la recherche et le clic) est un 404 qui dit quoi,
        # pas un 500 anonyme.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"œuvre inconnue : {geste.oeuvre_id}"
        ) from exc
    return {"oeuvreId": geste.oeuvre_id, "statut": geste.statut}


@router.get("/signaux")
async def lister(
    conn: Conn,
    signaux: SignauxDep,
    session_id: SessionOptionnelle,
    statut: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Les classements de la session — c'est ce que le composant recharge au
    retour du visiteur, pour rallumer les boutons des cartes."""
    if statut is not None and statut not in STATUTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"statut inconnu : {statut} (attendu : {', '.join(STATUTS)})",
        )
    if session_id is None:
        return {"items": []}
    return {"items": await signaux.lister(conn, session_id, statut=statut)}


@router.delete("/signaux/{oeuvre_id}")
async def retirer(
    conn: Conn, signaux: SignauxDep, session_id: SessionOptionnelle, oeuvre_id: int
) -> dict[str, Any]:
    """Le déclassement. Idempotent : retirer un signal absent n'est pas une
    erreur — le visiteur voulait qu'il n'y soit plus, il n'y est plus."""
    retire = session_id is not None and await signaux.retirer(conn, session_id, oeuvre_id=oeuvre_id)
    return {"oeuvreId": oeuvre_id, "retire": retire}
