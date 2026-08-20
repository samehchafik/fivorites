"""Les membres venus de la V1 : qui ils sont, ce qu'ils ont mis dans leurs tops.

Deux routes, en lecture pure, et le découpage suit l'usage : on cherche
quelqu'un dans une liste, puis on regarde ses tops. Charger les tops avec la
liste coûterait 324 000 positions pour en afficher cinq.

Le schéma `membre` n'est **pas** dans le `search_path` du pool (`sourcing`,
`admin`, `public`) : il est qualifié partout ici, et c'est volontaire. Il
appartient à la migration du sourcing, pas à l'administration ; le préfixe dit
qu'on lit chez le voisin.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from fiv_admin.deps import Conn, CurrentUser

router = APIRouter()

# Le tri se choisit dans une liste fermée : la valeur arrive dans un `order by`,
# donc elle ne peut pas être un paramètre lié. Une liste blanche est ici la
# seule défense qui vaille — pas un échappement.
TRIS = {
    "fives": "fives",
    "positions": "positions",
    "pseudo": "pseudo",
    "creation": "creation",
    "connexion": "derniere_connexion",
}


@router.get("/membres")
async def liste(
    user: CurrentUser,
    conn: Conn,
    q: Annotated[str | None, Query(max_length=120)] = None,
    tri: str = "fives",
    ordre: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    avecFives: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """La liste des membres : pseudo, email, nombre de tops.

    `q` cherche dans le pseudo **et** dans l'email. Les deux sont utiles pour
    des raisons différentes : 37 006 membres n'ont pas de compte donc pas
    d'email, et 945 n'ont pas de pseudo — chercher dans un seul champ laisserait
    une partie de la base introuvable.
    """
    colonne = TRIS.get(tri)
    if colonne is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"tri inconnu : {tri}")

    motif = f"%{q.strip()}%" if q and q.strip() else None

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            with compte as (
                -- Un seul balayage des tops et de leurs positions, plutôt
                -- qu'une sous-requête corrélée par membre : la liste se trie
                -- sur ces totaux, donc ils sont de toute façon tous calculés.
                select f.membre_id,
                       count(distinct f.id) as fives,
                       count(p.rang)        as positions
                  from membre.five f
                  left join membre.five_position p on p.five_id = f.id
                 where f.valide
                 group by f.membre_id
            ),
            base as (
                select m.id,
                       m.pseudo,
                       i.email,
                       m.bani,
                       m.valide,
                       m.masque,
                       m.creation,
                       m.derniere_connexion,
                       coalesce(c.fives, 0)     as fives,
                       coalesce(c.positions, 0) as positions
                  from membre.membre m
                  left join membre.identifiant i on i.membre_id = m.id
                  left join compte c             on c.membre_id = m.id
                 where (%(motif)s::text is null
                        or m.pseudo ilike %(motif)s
                        or i.email  ilike %(motif)s)
                   and (not %(avec_fives)s or coalesce(c.fives, 0) > 0)
            )
            select *, count(*) over () as total
              from base
             -- Le second critère n'est pas décoratif : sans lui, deux membres
             -- à égalité de tops changent d'ordre d'une page à l'autre, et la
             -- pagination affiche deux fois le même ou en saute un.
             order by {colonne} {ordre.upper()} NULLS LAST, id
             limit %(limite)s offset %(saut)s
            """,
            {
                "motif": motif,
                "avec_fives": avecFives,
                "limite": pageSize,
                "saut": (page - 1) * pageSize,
            },
        )
        lignes = await cur.fetchall()
        colonnes = [d.name for d in cur.description or []]

    items = [dict(zip(colonnes, ligne, strict=True)) for ligne in lignes]
    total = items[0].pop("total") if items else 0
    for item in items:
        item.pop("total", None)

    return {
        "items": [
            {
                "id": i["id"],
                "pseudo": i["pseudo"],
                "email": i["email"],
                "fives": i["fives"],
                "positions": i["positions"],
                "bani": i["bani"],
                "valide": i["valide"],
                "masque": i["masque"],
                "creation": i["creation"],
                "derniereConnexion": i["derniere_connexion"],
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/membres/{membre_id}/fives")
async def fives(user: CurrentUser, conn: Conn, membre_id: int) -> dict[str, Any]:
    """Les tops d'un membre, positions comprises, dans l'ordre du classement.

    Le titre affiché vient de trois sources, dans cet ordre : la fiche TMDB
    projetée, le pivot (pour les œuvres nées de la V1), et à défaut le
    `titre_saisi` conservé à l'import. Le dernier n'est pas un pis-aller : pour
    les 208 œuvres dont TMDB a supprimé la fiche, c'est la seule chose qui
    reste, et une ligne sans titre ferait croire à une position vide.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select m.id, m.pseudo, m.bani, m.valide, m.masque, m.creation,
                   m.derniere_connexion, i.email
              from membre.membre m
              left join membre.identifiant i on i.membre_id = m.id
             where m.id = %s
            """,
            (membre_id,),
        )
        tete = await cur.fetchone()
        if tete is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"membre inconnu : {membre_id}")

        await cur.execute(
            """
            select f.id            as five_id,
                   f.univers,
                   f.periode,
                   f.visibilite,
                   f.titre         as five_titre,
                   f.creation      as five_creation,
                   p.rang,
                   p.titre_saisi,
                   p.pourquoi,
                   p.commentaire,
                   o.id            as oeuvre_id,
                   o.id_tmdb,
                   coalesce(tv.name, mv.name, o.titre, p.titre_saisi) as titre,
                   coalesce(tv.poster_path, mv.poster_path)           as poster,
                   coalesce(
                       extract(year from tv.first_air_date)::int,
                       extract(year from mv.first_air_date)::int,
                       o.annee
                   )                                                  as annee,
                   coalesce(tv.vote_average, mv.vote_average)         as note
              from membre.five f
              left join membre.five_position p on p.five_id = f.id
              left join oeuvre o    on o.id = p.oeuvre_id
              left join tv_card tv  on f.univers = 'series' and tv.id = o.id_tmdb
              left join movie_card mv on f.univers = 'movies' and mv.id = o.id_tmdb
             where f.membre_id = %s
             order by f.univers, f.periode, f.id, p.rang
            """,
            (membre_id,),
        )
        lignes = await cur.fetchall()

    tops: dict[int, dict[str, Any]] = {}
    for (
        five_id,
        univers,
        periode,
        visibilite,
        five_titre,
        five_creation,
        rang,
        titre_saisi,
        pourquoi,
        commentaire,
        oeuvre_id,
        id_tmdb,
        titre,
        poster,
        annee,
        note,
    ) in lignes:
        top = tops.setdefault(
            five_id,
            {
                "id": five_id,
                "univers": univers,
                "periode": periode,
                "visibilite": visibilite,
                "titre": five_titre,
                "creation": five_creation,
                "positions": [],
            },
        )
        # Un top sans aucune position existe (862 à l'import) : le `left join`
        # rend alors une ligne à `rang` nul, qui n'est pas une position.
        if rang is None:
            continue
        top["positions"].append(
            {
                "rang": rang,
                "oeuvreId": oeuvre_id,
                "idTmdb": id_tmdb,
                "titre": titre,
                "titreSaisi": titre_saisi,
                "poster": poster,
                "annee": annee,
                "note": note,
                "pourquoi": pourquoi,
                "commentaire": commentaire,
            }
        )

    return {
        "membre": {
            "id": tete[0],
            "pseudo": tete[1],
            "bani": tete[2],
            "valide": tete[3],
            "masque": tete[4],
            "creation": tete[5],
            "derniereConnexion": tete[6],
            "email": tete[7],
        },
        "fives": list(tops.values()),
    }
