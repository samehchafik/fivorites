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
    # Répété : `?filtres=Drame&filtres=Comédie`. La dimension dépend de
    # l'univers (genres, ou langues pour les livres) — le client la découvre
    # par `/filtres`, il n'a pas à la connaître.
    filtres: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    texte = q.strip()
    if not texte:
        return {"items": [], "moteur": "aucun", "total": 0, "encore": False}

    choisis = [valeur for valeur in (filtres or []) if valeur.strip()]
    depuis = (page - 1) * taille

    trouvee = await moteur.page(univers, texte, taille=taille, depuis=depuis, filtres=choisis)
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
    return {
        "items": [carte.publique() for carte in hydratees],
        "moteur": source,
        "total": total,
        # Le total est-il un plancher (« au moins N ») ? Le composant écrit
        # alors « 500+ » plutôt qu'un décompte qu'ES n'a pas fait.
        "totalApproche": bool(trouvee and trouvee.tronque),
        "encore": encore,
        "page": page,
    }


@router.get("/filtres")
async def filtres(moteur: RechercheDep, univers: UniversDep) -> dict[str, Any]:
    """Les valeurs de filtre de cet univers, avec leur nombre d'œuvres.

    La dimension n'est pas la même partout et la réponse le dit : les genres
    pour les séries et les films, les langues pour les livres — qui n'ont
    aucun genre en base (voir `univers.champ_filtre`). Le front affiche le
    libellé qu'il reçoit ; il n'a aucune liste en dur.

    ES absent : une liste vide plutôt qu'une erreur. Le composant masque
    simplement ses cases — la recherche, elle, marche toujours.
    """
    trouvees = await moteur.facettes(univers)
    return {
        "dimension": univers.champ_filtre,
        "libelle": univers.label_filtre,
        "valeurs": [facette.publique() for facette in trouvees or []],
    }
