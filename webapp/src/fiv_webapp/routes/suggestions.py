"""L'onglet Mes suggestions : ce que le moteur propose à cette session.

La route ne calcule rien elle-même — les trois étages sont dans
`suggestions.Moteur` — elle assemble : les pivots de la session, l'appel, et
une réponse qui dit toujours POURQUOI elle est vide quand elle l'est. Une
liste vide sans raison ressemble à une panne ; avec la raison, c'est un état
du parcours.

Le graphe n'est plus une condition : sans lui, les deux sources qui en
dépendent sont sautées et les affinités répondent seules.

La route ne connaît plus les statuts un par un : elle passe au moteur la carte
complète des pivots par statut, et c'est lui qui décide de ce qui fait graine
et de ce que ça pèse — « vu et aimé » n'est pas « je veux voir », et cette
règle appartient au moteur, pas à la route.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

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
    # Les genres masqués, répétés : `?sans=Animation&sans=Comédie`. Un filtre
    # de présentation choisi à l'écran (« moins de dessins animés ») — il ne
    # touche pas au profil, seulement à ce qui s'affiche.
    sans: Annotated[list[str] | None, Query(max_length=20)] = None,
) -> dict[str, Any]:
    if session_id is None:
        return {"items": [], "raison": "aucune_session", "graine": 0}

    pivots = await signaux.pivots(conn, session_id)
    moteur = Moteur(recherche, cartes, graphe)
    retenues, raison = await moteur.pour(conn, univers, pivots_par_statut=pivots, sans_genres=sans)
    return {
        "items": [suggestion.publique(univers.slug) for suggestion in retenues],
        "raison": raison,
        # Le nombre de graines réellement retenues, pondérations comprises :
        # c'est ce que le moteur a eu pour travailler, et ce que le front dit
        # au visiteur quand la liste est courte.
        "graine": len(moteur.graines(pivots)),
    }
