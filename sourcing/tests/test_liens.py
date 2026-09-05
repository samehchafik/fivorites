"""La récolte des liens de plateformes : de la réponse SPARQL à la table.

Le client Wikidata est joué : ces tests verrouillent le tri des lignes, les
upserts et le rapport — pas le réseau. Le format réel de la réponse a été
relevé sur query.wikidata.org (Lucifer, 2026-09-01)."""

from __future__ import annotations

import pytest

from fiv_sourcing.http import FetchResult
from fiv_sourcing.liens import recolter

pytestmark = pytest.mark.anyio


def _reponse(bindings: list[dict]) -> FetchResult:
    return FetchResult(
        url="https://query.wikidata.org/sparql",
        status=200,
        payload={"results": {"bindings": bindings}},
        attempts=1,
    )


class FauxWikidata:
    def __init__(self, reponses: list[FetchResult]) -> None:
        self.reponses = reponses
        self.appels: list[dict] = []

    async def liens_plateformes_lot(self, ids, **proprietes) -> FetchResult:
        self.appels.append({"ids": list(ids), **proprietes})
        return self.reponses.pop(0)


async def _oeuvre(conn, id_tmdb: int, univers: str = "series") -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into tmdb_catalog (id, original_name, exported_on)"
            " values (%s, 'x', current_date) on conflict do nothing",
            (id_tmdb,),
        )
        await cur.execute(
            "insert into oeuvre (univers, id_tmdb) values (%s, %s) returning id",
            (univers, id_tmdb),
        )
        (oeuvre_id,) = await cur.fetchone()
    return oeuvre_id


async def test_la_recolte_pose_les_identifiants_et_rafraichit(conn) -> None:
    lucifer = await _oeuvre(conn, 63174)
    muette = await _oeuvre(conn, 999999)  # inconnue de Wikidata : aucune ligne

    faux = FauxWikidata(
        [
            _reponse(
                [
                    {
                        "tmdb": {"value": "63174"},
                        "netflix": {"value": "80057918"},
                        "prime": {"value": "B01AMXSQE6"},
                        "apple": {"value": "umc.cmc.3vmo"},
                    }
                ]
            )
        ]
    )
    rapport = await recolter(conn, faux, univers="series")

    # Les propriétés séries sont celles demandées au client.
    assert faux.appels[0]["propriete"] == "P4983"
    assert faux.appels[0]["disney"] == "P7596"
    assert rapport["liens"] == 3
    assert rapport["parPlateforme"] == {"netflix": 1, "prime": 1, "apple": 1}

    async with conn.cursor() as cur:
        await cur.execute(
            "select plateforme, identifiant from lien_plateforme"
            " where oeuvre_id = %s order by plateforme",
            (lucifer,),
        )
        assert await cur.fetchall() == [
            ("apple", "umc.cmc.3vmo"),
            ("netflix", "80057918"),
            ("prime", "B01AMXSQE6"),
        ]
        await cur.execute("select count(*) from lien_plateforme where oeuvre_id = %s", (muette,))
        assert (await cur.fetchone()) == (0,)

    # Rejouer avec un identifiant qui a changé : l'upsert rafraîchit, sans
    # doublon — c'est ce qui permet au nightly de repasser tous les jours.
    faux = FauxWikidata(
        [_reponse([{"tmdb": {"value": "63174"}, "netflix": {"value": "70143836"}}])]
    )
    await recolter(conn, faux, univers="series")
    async with conn.cursor() as cur:
        await cur.execute(
            "select identifiant from lien_plateforme"
            " where oeuvre_id = %s and plateforme = 'netflix'",
            (lucifer,),
        )
        assert (await cur.fetchone()) == ("70143836",)
        await cur.execute("select count(*) from lien_plateforme where oeuvre_id = %s", (lucifer,))
        assert (await cur.fetchone()) == (3,)


async def test_un_lot_en_erreur_est_compte_et_passe(conn) -> None:
    await _oeuvre(conn, 4280, univers="movies")
    faux = FauxWikidata([FetchResult(url="u", status=429, payload=None, attempts=3, error="rate")])
    rapport = await recolter(conn, faux, univers="movies")
    assert faux.appels[0]["propriete"] == "P4947"
    assert rapport["lotsEnErreur"] == 1
    assert rapport["liens"] == 0
