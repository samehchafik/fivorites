"""La filmographie : ce qui s'ouvre au clic sur un visage.

Une route, paginée par dix. Elle n'est pas sur le chemin critique de la
frappe — un clic, pas une touche — d'où le droit d'interroger le graphe.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from fiv_webapp.deps import CartesDep, Conn, GrapheOpt, RechercheDep
from fiv_webapp.personnes import CLE_VALIDE, PAGE_MAX, Personnes
from fiv_webapp.univers import univers_ou_400

router = APIRouter()


@router.get("/personne/{cle}")
async def personne(
    conn: Conn,
    recherche: RechercheDep,
    cartes: CartesDep,
    graphe: GrapheOpt,
    cle: str,
    page: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 1,
    # Les deux ne servent qu'au repli par l'index, quand le graphe manque :
    # sans lui on ne sait chercher que par le nom, et dans un seul univers.
    univers: Annotated[str | None, Query()] = None,
    nom: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    """Quelqu'un, sa photo, et une page de ses œuvres.

    `cle` est l'identité du graphe : `tmdb:1234` pour un crédit TMDB,
    `wd:Q535` pour un auteur venu de Wikidata. Les deux espaces de
    numérotation ne se croisent jamais, et c'est ce préfixe qui évite qu'un
    clic sur un acteur ouvre la filmographie d'un homonyme.
    """
    if not CLE_VALIDE.match(cle):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"clé de personne invalide : {cle} (attendu tmdb:… ou wd:…)",
        )
    demande = None
    if univers:
        try:
            demande = univers_ou_400(univers)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    lecteur = Personnes(recherche, cartes, graphe)
    trouvee = await lecteur.pour(conn, cle, page=page, univers=demande, nom=nom)
    if trouvee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"personne inconnue : {cle}")
    return trouvee.publique()
