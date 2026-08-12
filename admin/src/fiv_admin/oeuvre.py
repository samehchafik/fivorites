"""Le pivot d'identité, vu depuis l'administration : `id_tmdb ↔ oeuvre_id`.

Depuis le lot 12, la couche 2 range ses lignes sous `sourcing.oeuvre` et non
plus sous un identifiant TMDB. La raison est dans la migration : le même entier
désigne deux œuvres différentes selon l'univers — `1399` est Game of Thrones
côté séries et un tout autre film côté films — et une note rangée sous un
entier nu ne dit pas de quelle œuvre elle parle.

Deux vocabulaires cohabitent donc, et c'est voulu :

* le **brut** se lit par `(kind, id_tmdb)` — c'est ce que TMDB a servi, et
  `raw_source` n'a pas à connaître notre pivot ;
* la **notation** s'écrit par `oeuvre_id` — c'est notre identité, et elle
  survit à une œuvre que TMDB ne connaîtrait pas.

Ce module est la charnière entre les deux, et **il ne fait que lire** :
l'administration n'écrit jamais dans `sourcing`. Le pivot est créé par la
collecte, au moment où la fiche est téléchargée.
"""

from __future__ import annotations

import psycopg

UNIVERS_DEFAUT = "series"


class SansPivot(LookupError):
    """L'œuvre n'a pas de ligne dans `sourcing.oeuvre`.

    En pratique : sa fiche n'a jamais été collectée avec succès. Le message le
    dit, parce que le réflexe naturel devant « oeuvre_id introuvable » serait
    de chercher un bug de jointure.
    """

    def __init__(self, id_tmdb: int, univers: str) -> None:
        super().__init__(
            f"aucune œuvre au pivot pour {univers}/{id_tmdb} — "
            "la fiche n'a pas été collectée (`fiv-sourcing tmdb fetch --id`)"
        )
        self.id_tmdb = id_tmdb


async def pivot(
    conn: psycopg.AsyncConnection, id_tmdb: int, *, univers: str = UNIVERS_DEFAUT
) -> int:
    """`id_tmdb → oeuvre_id`. Lève `SansPivot` si l'œuvre n'est pas connue."""
    async with conn.cursor() as cur:
        await cur.execute(
            "select id from sourcing.oeuvre where univers = %s and id_tmdb = %s",
            (univers, id_tmdb),
        )
        row = await cur.fetchone()
    if row is None:
        raise SansPivot(id_tmdb, univers)
    return int(row[0])


async def pivots(
    conn: psycopg.AsyncConnection, ids: list[int], *, univers: str = UNIVERS_DEFAUT
) -> dict[int, int]:
    """`{id_tmdb: oeuvre_id}` pour un lot, en une requête.

    Les œuvres sans pivot sont simplement absentes du résultat : à l'échelle
    d'un lot, une œuvre non collectée se saute, elle n'interrompt pas les
    autres — c'est la même règle que pour un appel de juge qui échoue.
    """
    if not ids:
        return {}
    async with conn.cursor() as cur:
        await cur.execute(
            "select id_tmdb, id from sourcing.oeuvre where univers = %s and id_tmdb = any(%s)",
            (univers, ids),
        )
        return {int(row[0]): int(row[1]) for row in await cur.fetchall()}
