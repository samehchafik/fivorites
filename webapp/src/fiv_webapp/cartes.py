"""Les cartes de présentation : l'hydratation Postgres, et le repli sans ES.

Le contrat est celui de tout le dépôt : ES rend des ids classés, Postgres
hydrate l'affichage — les projections `admin.tv_card` / `movie_card` /
`livre_card` portent les mêmes colonnes d'un univers à l'autre, c'est ce qui
garde ici une seule requête pour les trois.

La carte publique est volontairement plus courte que la vignette d'admin :
ce qu'il faut pour reconnaître l'œuvre et la classer — titre, année, affiche,
genres, synopsis coupé côté front — plus le pivot, qui est l'identité que le
signal et le graphe manipulent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fiv_webapp.univers import Univers


@dataclass(frozen=True, slots=True)
class Carte:
    """Une œuvre, prête à afficher dans le composant de suggestion."""

    id: int
    oeuvre_id: int | None
    univers: str
    titre: str | None
    titre_original: str | None
    annee: int | None
    affiche: str | None
    synopsis: str | None
    genres: list[str]
    note: float | None

    def publique(self) -> dict[str, Any]:
        """La forme JSON de l'API — camelCase, comme les routes de l'admin."""
        return {
            "id": self.id,
            "oeuvreId": self.oeuvre_id,
            "univers": self.univers,
            "titre": self.titre,
            "titreOriginal": self.titre_original,
            "annee": self.annee,
            "affiche": self.affiche,
            "synopsis": self.synopsis,
            "genres": self.genres,
            "note": self.note,
        }


# Une ligne par vignette demandée. La jointure sur `oeuvre` rapporte le pivot —
# l'identité que le signal stocke et que le graphe connaît. Elle est `left` :
# une vignette dont le pivot n'existe pas encore s'affiche quand même, ses
# boutons de classement sont simplement inertes côté front (oeuvreId null).
_HYDRATATION = sql.SQL(
    """
    select v.id,
           {oeuvre_id}                                  as oeuvre_id,
           v.name                                       as titre,
           v.original_name                              as titre_original,
           extract(year from v.first_air_date)::int     as annee,
           nullif(v.poster_path, '')                    as affiche,
           nullif(btrim(coalesce(v.overview, '')), '')  as synopsis,
           v.vote_average                               as note,
           array(
               select g ->> 'name'
               from jsonb_array_elements(coalesce(v.genres, '[]'::jsonb)) g
               where nullif(btrim(g ->> 'name'), '') is not null
           )                                            as genres
    from {vue} v
    {jointure_oeuvre}
    where v.id = any (%(ids)s)
    """
)

# La recherche de repli, quand ES ne répond pas : l'ILIKE historique sur le
# titre projeté. Moins bon — deux champs au lieu de ~45 langues, balayage au
# lieu d'index de préfixes — mais toujours juste : mêmes vignettes, même tri
# de fond (les mieux votées d'abord).
_REPLI_ILIKE = sql.SQL(
    """
    select v.id
    from {vue} v
    where v.name ilike %(motif)s or v.original_name ilike %(motif)s
    order by v.vote_count desc nulls last, v.id
    limit %(taille)s
    """
)


class Cartes:
    """Les lectures Postgres du composant : hydrater une liste d'ids, et
    chercher sans ES quand il le faut."""

    def _requete_hydratation(self, univers: Univers) -> sql.Composed:
        vue = sql.Identifier("admin", univers.card_view)
        if univers.pivot_card:
            # Les vignettes des livres sont keyées par le pivot : il est déjà
            # là, pas de jointure à payer.
            return _HYDRATATION.format(
                vue=vue,
                oeuvre_id=sql.SQL("v.id"),
                jointure_oeuvre=sql.SQL(""),
            )
        return _HYDRATATION.format(
            vue=vue,
            oeuvre_id=sql.SQL("o.id"),
            jointure_oeuvre=sql.SQL(
                "left join oeuvre o on o.univers = %(interne)s and o.id_tmdb = v.id"
            ),
        )

    async def hydrater(
        self, conn: psycopg.AsyncConnection, univers: Univers, ids: list[int]
    ) -> list[Carte]:
        """Les cartes des `ids`, rendues DANS L'ORDRE DEMANDÉ.

        C'est ES qui classe ; un `where id = any(...)` rend les lignes dans un
        ordre quelconque, et le reclassement se fait ici — perdre l'ordre
        reviendrait à perdre la pertinence.
        """
        if not ids:
            return []
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                self._requete_hydratation(univers),
                {"ids": ids, "interne": univers.interne},
            )
            lignes = await cur.fetchall()

        par_id = {ligne["id"]: self._carte(ligne, univers) for ligne in lignes}
        return [par_id[i] for i in ids if i in par_id]

    async def chercher_sql(
        self, conn: psycopg.AsyncConnection, univers: Univers, texte: str, *, taille: int
    ) -> list[int]:
        """Les ids du repli ILIKE — la recherche quand ES ne répond pas."""
        async with conn.cursor() as cur:
            await cur.execute(
                _REPLI_ILIKE.format(vue=sql.Identifier("admin", univers.card_view)),
                {"motif": f"%{texte}%", "taille": taille},
            )
            return [ligne[0] for ligne in await cur.fetchall()]

    def _carte(self, ligne: dict[str, Any], univers: Univers) -> Carte:
        note = ligne.get("note")
        return Carte(
            id=ligne["id"],
            oeuvre_id=ligne.get("oeuvre_id"),
            univers=univers.slug,
            titre=ligne.get("titre"),
            titre_original=ligne.get("titre_original"),
            annee=ligne.get("annee"),
            affiche=ligne.get("affiche"),
            synopsis=ligne.get("synopsis"),
            genres=list(ligne.get("genres") or []),
            note=round(float(note), 1) if note is not None else None,
        )
