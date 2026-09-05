"""La récolte des identifiants de titre par plateforme, depuis Wikidata.

Le besoin : « maîtriser les liens sortants » ET viser la page EXACTE du
titre chez l'enseigne quand c'est possible. TMDB ne donne pas ces URL ;
Wikidata les porte en propriétés publiques, indexées par nos clés TMDB.
Cette récolte remplit `sourcing.lien_plateforme` — le site fait le reste
(lien exact si la ligne existe, recherche sinon).

Par lots de deux cents : le catalogue entier tient en quelques centaines de
requêtes SPARQL contre un service gratuit et partagé — le même argument que
`by_tmdb_lot`, la même retenue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import psycopg

from fiv_sourcing.sources.wikidata import WikidataClient

log = logging.getLogger(__name__)

# Les propriétés d'entrée et de sortie par univers — Disney+ et Apple TV
# distinguent séries et films, Netflix/Prime/Crunchyroll non. Les livres
# n'ont pas de plateforme de diffusion : ils ne sont pas récoltés.
PROPRIETES = {
    "series": {"propriete": "P4983", "disney": "P7596", "apple": "P9751"},
    "movies": {"propriete": "P4947", "disney": "P7595", "apple": "P9586"},
}

PLATEFORMES = ("netflix", "prime", "disney", "apple", "crunchyroll")

_UPSERT = """
    insert into lien_plateforme (oeuvre_id, plateforme, identifiant, maj)
    values (%(oeuvre_id)s, %(plateforme)s, %(identifiant)s, now())
    on conflict (oeuvre_id, plateforme) do update
      set identifiant = excluded.identifiant, maj = now()
"""


async def recolter(
    conn: psycopg.AsyncConnection,
    client: WikidataClient,
    *,
    univers: str,
    lot: int = 200,
    avancement: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Balaye toutes les œuvres à id TMDB de l'univers et pose leurs liens.

    Idempotent : un identifiant déjà connu est simplement rafraîchi. Un lot
    SPARQL qui échoue est compté et passé — la récolte suivante le
    rattrapera, rien n'est perdu.
    """
    proprietes = PROPRIETES[univers]
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, id_tmdb from oeuvre where univers = %s and id_tmdb is not null order by id",
            (univers,),
        )
        oeuvres = await cur.fetchall()
    par_tmdb = {str(id_tmdb): oeuvre_id for oeuvre_id, id_tmdb in oeuvres}

    poses = 0
    lots_en_erreur = 0
    par_plateforme: dict[str, int] = dict.fromkeys(PLATEFORMES, 0)
    ids = [id_tmdb for _, id_tmdb in oeuvres]
    for depart in range(0, len(ids), lot):
        tranche = ids[depart : depart + lot]
        resultat = await client.liens_plateformes_lot(tranche, **proprietes)
        if resultat.status != 200 or resultat.payload is None:
            lots_en_erreur += 1
            log.warning(
                "lot SPARQL %s-%s en erreur (%s) — repris à la prochaine récolte",
                depart,
                depart + len(tranche),
                resultat.status,
            )
            continue
        lignes = resultat.payload.get("results", {}).get("bindings", [])
        async with conn.cursor() as cur:
            for ligne in lignes:
                tmdb = ligne.get("tmdb", {}).get("value")
                oeuvre_id = par_tmdb.get(tmdb)
                if oeuvre_id is None:
                    continue
                for plateforme in PLATEFORMES:
                    identifiant = (ligne.get(plateforme, {}).get("value") or "").strip()
                    if not identifiant:
                        continue
                    await cur.execute(
                        _UPSERT,
                        {
                            "oeuvre_id": oeuvre_id,
                            "plateforme": plateforme,
                            "identifiant": identifiant,
                        },
                    )
                    poses += 1
                    par_plateforme[plateforme] += 1
        if avancement is not None:
            avancement(min(depart + len(tranche), len(ids)), len(ids))

    return {
        "univers": univers,
        "oeuvres": len(ids),
        "liens": poses,
        "lotsEnErreur": lots_en_erreur,
        "parPlateforme": {nom: n for nom, n in par_plateforme.items() if n},
    }
