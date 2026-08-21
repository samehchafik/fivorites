"""La dérivation d'actualité : les diffs de fiches, et leur rejeu.

Le contrat central est l'idempotence : `actualite` se reconstruit depuis le
brut, donc rejouer ne doit jamais doubler — et le curseur doit rendre la
reprise gratuite, pas approximative.
"""

from __future__ import annotations

from datetime import date

from fiv_sourcing import store
from fiv_sourcing.actualite import deriver_diffs, diff_evenements
from fiv_sourcing.sources.tmdb.export import load_catalog


# ------------------------------------------------------------- fonction pure
def test_une_saison_qui_apparait_est_une_annonce():
    avant = {"seasons": [{"season_number": 1}], "status": "Returning Series"}
    apres = {
        "seasons": [{"season_number": 1}, {"season_number": 2, "air_date": "2026-09-01"}],
        "status": "Returning Series",
    }
    evenements = diff_evenements("tv", avant, apres, date(2026, 8, 18))
    assert evenements == [("saison_annoncee", date(2026, 9, 1), "Saison 2 annoncée")]


def test_deux_saisons_font_une_seule_annonce():
    """La clé (raw_source_id, type) impose un événement par type et par diff —
    et c'est aussi ce qu'un lecteur attend : une ligne, pas deux."""
    avant = {"seasons": []}
    apres = {"seasons": [{"season_number": 1}, {"season_number": 2}]}
    evenements = diff_evenements("tv", avant, apres, date(2026, 8, 18))
    assert len(evenements) == 1
    assert evenements[0][2] == "Saisons 1 et 2 annoncées"


def test_la_saison_zero_n_est_pas_une_annonce():
    """TMDB y range bêtisiers et épisodes spéciaux : du rangement, pas une
    nouvelle."""
    avant = {"seasons": [{"season_number": 1}]}
    apres = {"seasons": [{"season_number": 0}, {"season_number": 1}]}
    assert diff_evenements("tv", avant, apres, date(2026, 8, 18)) == []


def test_le_statut_qui_bascule_se_type():
    avant = {"status": "Returning Series", "last_air_date": "2026-05-01"}
    fin = diff_evenements("tv", avant, {**avant, "status": "Ended"}, date(2026, 8, 18))
    assert fin[0][0] == "diffusion_terminee"
    assert fin[0][1] == date(2026, 5, 1), "la date de fin est celle du dernier épisode"
    annule = diff_evenements("tv", avant, {**avant, "status": "Canceled"}, date(2026, 8, 18))
    assert annule[0][0] == "annulation"


def test_une_date_de_sortie_posee_est_une_sortie():
    evenements = diff_evenements(
        "movie", {"release_date": ""}, {"release_date": "2026-12-25"}, date(2026, 8, 18)
    )
    assert evenements == [("sortie", date(2026, 12, 25), "Sortie le 25/12/2026")]


def test_une_fiche_identique_ne_dit_rien():
    fiche = {"seasons": [{"season_number": 1}], "status": "Ended", "last_air_date": "2020-01-01"}
    assert diff_evenements("tv", fiche, dict(fiche), date(2026, 8, 18)) == []


def test_une_fiche_malformee_ne_plante_pas():
    """Un diff qui planterait sur une fiche mal remplie s'arrêterait au milieu
    du catalogue. Les dates vides, partielles ou absurdes rendent None."""
    avant = {"seasons": "pas une liste", "status": None}
    apres = {
        "seasons": [{"season_number": 2, "air_date": "n/a"}],
        "next_episode_to_air": {"air_date": ""},
        "status": "Ended",
        "last_air_date": "9999-99",
    }
    evenements = diff_evenements("tv", avant, apres, date(2026, 8, 18))
    types = {e[0] for e in evenements}
    assert "saison_annoncee" in types
    assert "diffusion_terminee" in types
    # Les dates invalides retombent sur le jour de collecte.
    assert all(e[1] == date(2026, 8, 18) for e in evenements)


# ----------------------------------------------------------------- en base
async def _fiche(conn, id_tmdb: int, payload: dict, *, kind: str = "tv") -> None:
    await store.store_raw(
        conn,
        source="tmdb",
        kind=kind,
        source_id=str(id_tmdb),
        lang="fr-FR",
        http_status=200,
        payload=payload,
    )


async def test_le_cycle_complet_derive_lie_et_ne_double_jamais(conn):
    await load_catalog(
        conn, iter([{"id": 1399, "original_name": "GoT", "popularity": 1.0}]), date(2026, 8, 6)
    )
    await _fiche(conn, 1399, {"id": 1399, "seasons": [{"season_number": 1}]})
    await _fiche(
        conn,
        1399,
        {
            "id": 1399,
            "seasons": [{"season_number": 1}, {"season_number": 2, "air_date": "2026-09-01"}],
        },
    )

    premier = await deriver_diffs(conn)
    assert premier.sans_precedent == 1, "la première collecte n'est pas une nouvelle"
    assert premier.evenements == 1
    assert premier.par_type == {"saison_annoncee": 1}

    async with conn.cursor() as cur:
        await cur.execute(
            "select a.type_evenement, a.survenu_le, o.univers, o.id_tmdb"
            " from actualite a join oeuvre o on o.id = a.oeuvre_id"
        )
        lignes = await cur.fetchall()
    assert lignes == [("saison_annoncee", date(2026, 9, 1), "series", 1399)], (
        "l'événement doit être lié au pivot, avec une liaison certaine"
    )

    # Le rejeu depuis zéro : le curseur repart, les clés naturelles retiennent.
    async with conn.cursor() as cur:
        await cur.execute("update actualite_curseur set dernier_raw_id = 0")
    second = await deriver_diffs(conn)
    assert second.examines == 2, "le curseur remis à zéro rejoue tout"
    assert second.evenements == 0, "rejouer ne double jamais"
    async with conn.cursor() as cur:
        await cur.execute("select count(*) from actualite")
        assert (await cur.fetchone())[0] == 1


async def test_le_film_et_la_serie_homonymes_ont_chacun_leur_actualite(conn):
    """Les deux catalogues TMDB se chevauchent : le diff d'un film doit se
    comparer aux fiches FILM, et se lier au pivot film."""
    from fiv_sourcing.univers import FILMS

    await load_catalog(
        conn,
        iter([{"id": 550, "original_name": "Une série", "popularity": 1.0}]),
        date(2026, 8, 6),
    )
    await load_catalog(
        conn,
        iter([{"id": 550, "original_title": "Fight Club", "popularity": 1.0}]),
        date(2026, 8, 6),
        univers=FILMS,
    )
    # La série 550 change de statut ; le film 550 gagne une date de sortie.
    await _fiche(conn, 550, {"id": 550, "status": "Returning Series"})
    await _fiche(conn, 550, {"id": 550, "status": "Ended", "last_air_date": "2026-01-01"})
    await _fiche(conn, 550, {"id": 550, "release_date": ""}, kind="movie")
    await _fiche(conn, 550, {"id": 550, "release_date": "2026-12-25"}, kind="movie")

    report = await deriver_diffs(conn)
    assert report.par_type == {"diffusion_terminee": 1, "sortie": 1}

    async with conn.cursor() as cur:
        await cur.execute(
            "select o.univers, a.type_evenement from actualite a"
            " join oeuvre o on o.id = a.oeuvre_id order by o.univers"
        )
        lignes = await cur.fetchall()
    assert lignes == [("movies", "sortie"), ("series", "diffusion_terminee")], (
        "chaque événement doit rejoindre le pivot de SON univers"
    )
