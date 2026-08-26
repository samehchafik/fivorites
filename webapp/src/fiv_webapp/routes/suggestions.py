"""L'onglet Mes suggestions : ce que le moteur propose à cette session.

La route ne calcule rien elle-même — les trois étages sont dans
`suggestions.Moteur` — elle assemble : les pivots de la session, l'appel, et
une réponse qui dit toujours POURQUOI elle est vide quand elle l'est. Une
liste vide sans raison ressemble à une panne ; avec la raison, c'est un état
du parcours.

Le graphe n'est plus une condition : sans lui, les deux premiers étages sont
sautés et les affinités répondent seules. C'est ce qui a changé le jour où
l'on a constaté que l'onglet restait vide sur une œuvre ordinaire.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from fiv_webapp.deps import (
    CartesDep,
    Conn,
    GrapheOpt,
    RechercheDep,
    SessionOptionnelle,
    SignauxDep,
    UniversDep,
)
from fiv_webapp.suggestions import Moteur

router = APIRouter()


@router.get("/suggestions")
async def suggestions(
    conn: Conn,
    graphe: GrapheOpt,
    recherche: RechercheDep,
    cartes: CartesDep,
    signaux: SignauxDep,
    session_id: SessionOptionnelle,
    univers: UniversDep,
) -> dict[str, Any]:
    if session_id is None:
        return {"items": [], "raison": "aucune_session", "graine": 0}

    pivots = await signaux.pivots(conn, session_id)
    aimes = pivots["aime"]
    exclues = [oeuvre for groupe in pivots.values() for oeuvre in groupe]

    moteur = Moteur(recherche, cartes, graphe)
    retenues, raison = await moteur.pour(conn, univers, aimes=aimes, exclues=exclues)
    return {
        "items": [suggestion.publique(univers.slug) for suggestion in retenues],
        "raison": raison,
        "graine": len(aimes),
    }
