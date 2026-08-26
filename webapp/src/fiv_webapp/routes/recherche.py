"""L'onglet Recherche : la frappe, les filtres, les cartes.

Deux routes, toutes deux sur le chemin critique du composant — chaque frappe
(débouncée côté front) passe par la première. ES classe, Postgres hydrate ;
quand ES ne répond pas, l'ILIKE prend le relais, paginé et filtré comme lui,
et la réponse dit avec quel moteur elle a été servie.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from fiv_webapp.deps import CartesDep, Conn, RechercheDep, UniversDep
from fiv_webapp.recherche import LANGUES, langue_servie

router = APIRouter()

# Une page de frappe. Courte, parce qu'on lit des cartes, pas un tableau — et
# paginée depuis qu'on a constaté que douze résultats sans suite laissaient
# croire que le catalogue s'arrêtait là.
TAILLE_MAX = 48
TAILLE_DEFAUT = 12

# Le composant ne déroule pas l'infini : au-delà, une frappe demande à être
# précisée, pas paginée (et ES refuse `from + size` au-delà de 10 000).
PAGE_MAX = 40


@router.get("/recherche")
async def recherche(
    conn: Conn,
    moteur: RechercheDep,
    cartes: CartesDep,
    univers: UniversDep,
    q: Annotated[str, Query(min_length=1, max_length=120)],
    taille: Annotated[int, Query(ge=1, le=TAILLE_MAX)] = TAILLE_DEFAUT,
    page: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 1,
    # Un paramètre par dimension, répété : `?genres=Drame&genres=Comédie
    # &plateformes=Netflix`. Les dimensions d'un univers se découvrent par
    # `/filtres` — le client n'en connaît aucune d'avance.
    genres: Annotated[list[str] | None, Query()] = None,
    plateformes: Annotated[list[str] | None, Query()] = None,
    # La langue de qui cherche. Le front la déduit du navigateur et laisse en
    # changer ; le serveur retient celle qu'il sert, ou le français.
    langue: Annotated[str | None, Query(max_length=10)] = None,
) -> dict[str, Any]:
    texte = q.strip()
    retenue = langue_servie(langue)
    if not texte:
        return {
            "items": [],
            "moteur": "aucun",
            "langue": retenue,
            "langues": list(LANGUES),
            "total": 0,
            "encore": False,
        }

    choisis = [valeur for valeur in (filtres or []) if valeur.strip()]
    depuis = (page - 1) * taille

    trouvee = await moteur.page(
        univers, texte, taille=taille, depuis=depuis, langue=retenue, filtres=choisis
    )
    if trouvee is None:
        ids = await cartes.chercher_sql(
            conn, univers, texte, taille=taille, depuis=depuis, filtres=choisis
        )
        source = "sql"
        # Sans compteur en repli : une page pleine veut dire « il en reste
        # peut-être », une page creuse veut dire « c'est tout ». Honnête, et
        # ça évite un `count(*)` sur un balayage déjà lent.
        total = depuis + len(ids)
        encore = len(ids) == taille
    else:
        ids = trouvee.ids
        source = "es"
        total = trouvee.total
        encore = depuis + len(ids) < total and page < PAGE_MAX

    hydratees = await cartes.hydrater(conn, univers, ids)
    # Le titre dans la langue demandée remplace celui de la projection, qui
    # n'en porte qu'une — celle de la collecte, le français. Afficher « Le
    # Fils de Sam » à qui cherche en arabe est ce qui faisait conclure à un
    # bug, et c'était une conclusion raisonnable.
    localises = trouvee.titres if trouvee else {}
    items = []
    for carte in hydratees:
        publique = carte.publique()
        if localises.get(carte.id):
            publique["titre"] = localises[carte.id]
        items.append(publique)

    return {
        "items": items,
        "moteur": source,
        "langue": retenue,
        "langues": list(LANGUES),
        "total": total,
        # Le total est-il un plancher (« au moins N ») ? Le composant écrit
        # alors « 500+ » plutôt qu'un décompte qu'ES n'a pas fait.
        "totalApproche": bool(trouvee and trouvee.tronque),
        "encore": encore,
        "page": page,
    }


@router.get("/filtres")
async def filtres(
    moteur: RechercheDep,
    univers: UniversDep,
    langue: Annotated[str | None, Query(max_length=10)] = None,
) -> dict[str, Any]:
    """Les dimensions de filtre de cet univers, chacune avec ses valeurs.

    Plusieurs groupes, et pas les mêmes partout : les séries et les films
    portent les genres ET les plateformes, un livre ne se regarde pas sur
    Netflix. Le front affiche les libellés qu'il reçoit ; il n'a aucune liste
    en dur, ce qui lui évite d'inventer une case que le catalogue ne remplit
    pas.

    La langue compte : les plateformes sont indexées par pays, et « Netflix »
    en France n'est pas « Shahid » en Arabie saoudite.

    ES absent : des groupes vides plutôt qu'une erreur. Le composant masque
    ses cases — la recherche, elle, marche toujours.
    """
    retenue = langue_servie(langue)
    trouvees = await moteur.facettes(univers, langue=retenue) or {}
    return {
        "langue": retenue,
        "groupes": [
            {
                "champ": dimension.champ,
                "libelle": dimension.libelle,
                "valeurs": [facette.publique() for facette in trouvees.get(dimension.champ, [])],
            }
            for dimension in univers.dimensions
        ],
    }
