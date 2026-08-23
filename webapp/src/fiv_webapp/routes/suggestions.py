"""L'onglet Mes suggestions : ce que le graphe propose à cette session.

La route ne calcule rien elle-même — le moteur est dans `suggestions.py`,
elle assemble : les pivots de la session, l'appel au graphe, et une réponse
qui dit toujours POURQUOI elle est vide quand elle l'est. Une liste vide sans
raison ressemble à une panne ; avec la raison, c'est un état du parcours.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from fiv_webapp.deps import Conn, GrapheOpt, SessionOptionnelle, SignauxDep, UniversDep
from fiv_webapp.suggestions import Suggestions

router = APIRouter()


@router.get("/suggestions")
async def suggestions(
    conn: Conn,
    graphe: GrapheOpt,
    signaux: SignauxDep,
    session_id: SessionOptionnelle,
    univers: UniversDep,
) -> dict[str, Any]:
    if graphe is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "graphe non configuré (NEO4J_URL, NEO4J_PASSWORD)",
        )

    if session_id is None:
        return {"items": [], "raison": "aucune_session"}

    pivots = await signaux.pivots(conn, session_id)
    aimes = pivots["aime"]
    if not aimes:
        return {"items": [], "raison": "aucun_aime"}

    exclues = [oeuvre for groupe in pivots.values() for oeuvre in groupe]
    moteur = Suggestions(graphe)
    retenues = await moteur.pour(aimes=aimes, exclues=exclues, univers_interne=univers.interne)
    return {
        "items": [suggestion.publique(univers.slug) for suggestion in retenues],
        "raison": None if retenues else "aucun_resultat",
        "graine": len(aimes),
    }
