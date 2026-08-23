"""L'onglet Recherche : la frappe, les cartes.

Une seule route, et elle est sur le chemin critique du composant — chaque
frappe (débouncée côté front) passe ici. ES classe, Postgres hydrate ; quand
ES ne répond pas, l'ILIKE prend le relais et la réponse dit avec quel moteur
elle a été servie — le front n'en fait rien, mais un œil sur les temps de
réponse voudra savoir lequel il mesure.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from fiv_webapp.deps import CartesDep, Conn, RechercheDep, UniversDep

router = APIRouter()

# Une page de frappe : assez pour choisir, pas de pagination (voir
# `recherche.py` — si le résultat n'y est pas, on précise la requête).
TAILLE_MAX = 30
TAILLE_DEFAUT = 12


@router.get("/recherche")
async def recherche(
    conn: Conn,
    moteur: RechercheDep,
    cartes: CartesDep,
    univers: UniversDep,
    q: Annotated[str, Query(min_length=1, max_length=120)],
    taille: Annotated[int, Query(ge=1, le=TAILLE_MAX)] = TAILLE_DEFAUT,
) -> dict[str, Any]:
    texte = q.strip()
    if not texte:
        return {"items": [], "moteur": "aucun"}

    ids = await moteur.ids(univers, texte, taille=taille)
    if ids is None:
        ids = await cartes.chercher_sql(conn, univers, texte, taille=taille)
        source = "sql"
    else:
        source = "es"

    hydratees = await cartes.hydrater(conn, univers, ids)
    return {"items": [carte.publique() for carte in hydratees], "moteur": source}
