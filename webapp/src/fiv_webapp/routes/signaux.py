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

from fiv_webapp.deps import (
    Conn,
    RechercheDep,
    SessionGarantie,
    SessionOptionnelle,
    SignauxDep,
    univers_demande,
)
from fiv_webapp.recherche import LANGUES, Recherche, langue_servie
from fiv_webapp.signaux import STATUTS
from fiv_webapp.univers import UNIVERS

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
    moteur: RechercheDep,
    session_id: SessionOptionnelle,
    statut: Annotated[str | None, Query()] = None,
    # La langue de qui relit sa liste. Facultative : le composant l'envoie
    # pour afficher « Ma liste », et ne l'envoie pas quand il ne recharge que
    # les statuts au montage — un `_mget` par univers pour rallumer trois
    # boutons serait payé pour rien.
    langue: Annotated[str | None, Query(max_length=10)] = None,
) -> dict[str, Any]:
    """Les classements de la session — c'est ce que le composant recharge au
    retour du visiteur, pour rallumer les boutons des cartes, et ce que
    l'onglet « Ma liste » affiche.

    Les titres viennent de la projection, donc en français ; avec `langue`,
    ils sont remplacés par ceux de l'index — sa liste doit se relire dans la
    langue qu'on a choisie, comme la recherche.
    """
    if statut is not None and statut not in STATUTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"statut inconnu : {statut} (attendu : {', '.join(STATUTS)})",
        )
    if session_id is None:
        return {"items": [], "langue": langue_servie(langue), "langues": list(LANGUES)}
    items = await signaux.lister(conn, session_id, statut=statut)
    retenue = langue_servie(langue)
    if langue is not None:
        await _localiser(moteur, items, langue=retenue)
    return {"items": items, "langue": retenue, "langues": list(LANGUES)}


async def _localiser(moteur: Recherche, items: list[dict[str, Any]], *, langue: str) -> None:
    """Remplace sur place les titres par ceux de l'index, un univers à la fois.

    Un appel par univers présent, pas un par œuvre : une session mélange les
    trois, et `_mget` prend une liste de clés.
    """
    par_univers: dict[str, list[int]] = {}
    for item in items:
        if item.get("id") is not None and item["univers"] in UNIVERS:
            par_univers.setdefault(item["univers"], []).append(int(item["id"]))
    for slug, cles in par_univers.items():
        trouves = await moteur.titres(UNIVERS[slug], cles, langue=langue)
        for item in items:
            if item["univers"] == slug and trouves.get(item.get("id")):
                item["titre"] = trouves[item["id"]]


@router.delete("/signaux/{oeuvre_id}")
async def retirer(
    conn: Conn, signaux: SignauxDep, session_id: SessionOptionnelle, oeuvre_id: int
) -> dict[str, Any]:
    """Le déclassement. Idempotent : retirer un signal absent n'est pas une
    erreur — le visiteur voulait qu'il n'y soit plus, il n'y est plus."""
    retire = session_id is not None and await signaux.retirer(conn, session_id, oeuvre_id=oeuvre_id)
    return {"oeuvreId": oeuvre_id, "retire": retire}
