"""La fiche détaillée : ce qui s'ouvre quand on clique une carte.

Une seule route, en lecture pure. Elle n'est pas sur le chemin critique de la
frappe — un clic, pas une touche — d'où le droit de relire le brut plutôt que
la projection : c'est ce qui permet de montrer les saisons et la distribution,
qu'aucune vignette ne porte.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from fiv_webapp.deps import Conn, FichesDep, UniversDep

router = APIRouter()


@router.get("/fiche/{identifiant}")
async def fiche(
    conn: Conn, fiches: FichesDep, univers: UniversDep, identifiant: int
) -> dict[str, Any]:
    """L'œuvre en grand. `identifiant` est la clé de la vignette — id TMDB
    pour séries et films, pivot pour les livres — celle que la carte porte."""
    trouvee = await fiches.pour(conn, univers, identifiant)
    if trouvee is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"œuvre inconnue dans {univers.slug} : {identifiant}",
        )
    return trouvee.publique()
