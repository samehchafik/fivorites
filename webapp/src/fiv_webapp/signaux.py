"""Les signaux de goût d'une session : poser, retirer, relire.

Trois statuts, exclusifs par construction (la clé primaire de
`visiteur.signal` est le couple session × œuvre) :

* `aime` — « j'ai vu et aimé » : c'est LA matière des suggestions ;
* `aime_pas` — « je n'aime pas » : n'alimente rien, mais exclut l'œuvre des
  suggestions — on ne repropose pas ce qui a été écarté ;
* `a_voir` — « je veux voir » : la liste d'envies ; exclue des suggestions
  aussi, puisque c'est une suggestion déjà acceptée.

L'identité manipulée est le pivot `sourcing.oeuvre.id` — jamais un id TMDB :
c'est la seule clé commune aux trois univers et c'est celle du graphe.
"""

from __future__ import annotations

from typing import Any

import psycopg

from fiv_webapp.univers import univers_de_interne

STATUTS = ("aime", "aime_pas", "a_voir")

# La relecture hydrate l'affichage depuis les trois projections d'un coup :
# une session mélange les univers, et trois requêtes par onglet coûteraient
# plus cher que trois `left join` sur des vues indexées par leur clé.
_LISTE = """
    select s.oeuvre_id,
           s.univers,
           s.statut,
           coalesce(tv.id, mv.id, lv.id)                          as vignette,
           coalesce(tv.name, mv.name, lv.name, o.titre)           as titre,
           nullif(coalesce(tv.poster_path, mv.poster_path, lv.poster_path), '') as affiche,
           coalesce(extract(year from tv.first_air_date)::int,
                    extract(year from mv.first_air_date)::int,
                    extract(year from lv.first_air_date)::int,
                    o.annee)                                       as annee
    from visiteur.signal s
    join oeuvre o        on o.id = s.oeuvre_id
    left join tv_card tv    on s.univers = 'series' and tv.id = o.id_tmdb
    left join movie_card mv on s.univers = 'movies' and mv.id = o.id_tmdb
    left join livre_card lv on s.univers = 'livres' and lv.id = o.id
    where s.session_id = %(session_id)s
      and (%(statut)s::text is null or s.statut = %(statut)s)
    order by s.creation desc
"""


class Signaux:
    """Les écritures et lectures de `visiteur.signal`, pour une session."""

    async def poser(
        self,
        conn: psycopg.AsyncConnection,
        session_id: str,
        *,
        oeuvre_id: int,
        univers_interne: str,
        statut: str,
    ) -> None:
        """Pose ou reclasse : un signal par œuvre, le dernier geste gagne."""
        if statut not in STATUTS:
            raise ValueError(f"statut inconnu : {statut} (attendu : {', '.join(STATUTS)})")
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into visiteur.signal (session_id, oeuvre_id, univers, statut)
                values (%(session_id)s, %(oeuvre_id)s, %(univers)s, %(statut)s)
                on conflict (session_id, oeuvre_id)
                do update set statut = excluded.statut, creation = now()
                """,
                {
                    "session_id": session_id,
                    "oeuvre_id": oeuvre_id,
                    "univers": univers_interne,
                    "statut": statut,
                },
            )
            # L'activité de la session, tenue au fil des gestes : c'est elle
            # qui permettra un jour de balayer les sessions mortes.
            await cur.execute(
                "update visiteur.session set derniere_activite = now() where id = %s",
                (session_id,),
            )

    async def retirer(
        self, conn: psycopg.AsyncConnection, session_id: str, *, oeuvre_id: int
    ) -> bool:
        """Retire le signal — le visiteur a déclassé l'œuvre. Vrai s'il y
        avait quelque chose à retirer."""
        async with conn.cursor() as cur:
            await cur.execute(
                "delete from visiteur.signal where session_id = %s and oeuvre_id = %s",
                (session_id, oeuvre_id),
            )
            return cur.rowcount > 0

    async def lister(
        self, conn: psycopg.AsyncConnection, session_id: str, *, statut: str | None = None
    ) -> list[dict[str, Any]]:
        """Les signaux de la session, hydratés pour l'affichage, les plus
        récents d'abord."""
        async with conn.cursor() as cur:
            await cur.execute(_LISTE, {"session_id": session_id, "statut": statut})
            lignes = await cur.fetchall()
        # `id` est la clé de VIGNETTE, celle que la fiche demande — sans elle,
        # une œuvre de la liste s'affichait sans pouvoir s'ouvrir. Elle peut
        # manquer : un pivot dont la projection n'a pas (encore) de ligne
        # reste listé, simplement pas cliquable.
        return [
            {
                "id": vignette,
                "oeuvreId": oeuvre_id,
                "univers": (trouve.slug if (trouve := univers_de_interne(univers)) else univers),
                "statut": statut_ligne,
                "titre": titre,
                "affiche": affiche,
                "annee": annee,
            }
            for oeuvre_id, univers, statut_ligne, vignette, titre, affiche, annee in lignes
        ]

    async def pivots(self, conn: psycopg.AsyncConnection, session_id: str) -> dict[str, list[int]]:
        """Les pivots de la session, groupés par statut — la forme que le
        moteur de suggestions consomme : `aime` est sa graine, l'union des
        trois son exclusion."""
        async with conn.cursor() as cur:
            await cur.execute(
                "select statut, oeuvre_id from visiteur.signal where session_id = %s",
                (session_id,),
            )
            lignes = await cur.fetchall()
        groupes: dict[str, list[int]] = {statut: [] for statut in STATUTS}
        for statut, oeuvre_id in lignes:
            groupes[statut].append(oeuvre_id)
        return groupes

    async def creer_session(self, conn: psycopg.AsyncConnection) -> str:
        """Une session anonyme neuve. Rendue en texte : c'est la forme que le
        jeton transporte et que toutes les requêtes lient."""
        async with conn.cursor() as cur:
            await cur.execute("insert into visiteur.session default values returning id")
            ligne = await cur.fetchone()
        return str(ligne[0])

    async def session_existe(self, conn: psycopg.AsyncConnection, session_id: str) -> bool:
        """Le jeton peut être authentique et la ligne absente — base de dev
        recréée, purge future des sessions mortes. On vérifie plutôt que de
        laisser la première écriture échouer sur une clé étrangère."""
        async with conn.cursor() as cur:
            await cur.execute("select 1 from visiteur.session where id = %s", (session_id,))
            return await cur.fetchone() is not None
