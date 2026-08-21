"""Le JSON canonique — R5 : mêmes clés partout, jamais de clé inventée.

Pas de réseau, pas de base. Ces tests sont le contrat de `normalize.py` : si
une source veut apporter une donnée nouvelle, c'est ici qu'on le voit.
"""

from __future__ import annotations

import pytest

from fiv_sourcing import normalize

WIKIDATA_COMPLET = {
    "qid": "Q23572",
    "imdb": "tt0944947",
    "tvmaze": "82",
    "pays": ["US", "GB"],
    "langues": ["en"],
    "lieux_tournage": ["Belfast"],
    "lieux_action": ["Westeros"],
}

TVMAZE_COMPLET = {
    "id": 82,
    "nom": "Game of Thrones",
    "statut": "Ended",
    "premiere": "2011-04-17",
    "diffuseur": "HBO",
    "pays": "US",
    "calendrier": {"days": ["Sunday"], "time": "21:00"},
    "episodes": 73,
    "episodes_dates": 73,
    "episodes_resumes": 73,
    "imdb": "tt0944947",
}


WIKIDATA_LIVRE_COMPLET = {
    "qid": "Q189378",
    "olid": "OL27258W",
    "auteurs": [{"qid": "Q5878", "nom": "Gabriel García Márquez"}],
    "langues": ["es"],
    "pays": ["CO"],
    "annee": 1967,
}

OPENLIBRARY_WORK = {
    "olid": "OL27258W",
    "titre": "Cien años de soledad",
    "description": "Un roman.",
}

OPENLIBRARY_EDITIONS = {
    "editions": [
        {"langue": "es", "nombre": 7, "isbn": "9780307474728", "annee": 1967},
        {"langue": "fr", "nombre": 5, "isbn": "9782020238113", "annee": 1995},
    ],
    "total": 64,
    "sans_langue": 15,
    "tronque": False,
}


@pytest.mark.parametrize(
    "canonique",
    [
        normalize.depuis_wikidata(WIKIDATA_COMPLET),
        normalize.depuis_tvmaze(TVMAZE_COMPLET),
        normalize.depuis_wikidata_livre(WIKIDATA_LIVRE_COMPLET),
        normalize.depuis_openlibrary(OPENLIBRARY_WORK, OPENLIBRARY_EDITIONS),
    ],
    ids=["wikidata", "tvmaze", "wikidata-livre", "openlibrary"],
)
def test_aucune_cle_hors_schema(canonique):
    """La règle qui rend le JSON uniforme : une source qui veut une clé nouvelle
    doit l'ajouter au schéma canonique, pas l'inventer dans son coin."""
    assert set(canonique) <= normalize.CLES


def test_wikidata_produit_les_faits_attendus():
    canonique = normalize.depuis_wikidata(WIKIDATA_COMPLET)

    assert canonique == {
        "pays": ["US", "GB"],
        "langues": ["en"],
        "lieux": [
            {"type": "tournage", "nom": "Belfast"},
            {"type": "action", "nom": "Westeros"},
        ],
        "ids": {"wikidata": "Q23572", "imdb": "tt0944947", "tvmaze": 82},
    }


def test_tvmaze_produit_les_faits_attendus():
    canonique = normalize.depuis_tvmaze(TVMAZE_COMPLET)

    assert canonique == {
        "titre": "Game of Thrones",
        "annee": 2011,
        "statut": "terminee",
        "pays": ["US"],
        "diffuseur": "HBO",
        "calendrier": {"jours": ["Sunday"], "heure": "21:00"},
        "episodes": {"total": 73, "dates": 73, "resumes": 73},
        "ids": {"tvmaze": 82, "imdb": "tt0944947"},
    }


def test_une_valeur_absente_est_une_cle_absente():
    """Jamais de null ni de liste vide de remplissage : une clé présente veut
    dire « on sait », une clé absente « on ne sait pas ». Les confondre rendrait
    la couche 1 incapable de distinguer les deux."""
    assert normalize.depuis_wikidata({"qid": "Q1"}) == {"ids": {"wikidata": "Q1"}}
    assert normalize.depuis_tvmaze({"id": 5}) == {"ids": {"tvmaze": 5}}


def test_un_statut_incertain_reste_absent():
    """« To Be Determined » n'est pas un statut de diffusion, c'est une
    incertitude — l'inventer fausserait la facette « série terminée »."""
    assert "statut" not in normalize.depuis_tvmaze({"id": 1, "statut": "To Be Determined"})
    assert normalize.depuis_tvmaze({"id": 1, "statut": "Running"})["statut"] == "en_cours"


def test_l_annee_vient_de_la_date_de_premiere():
    assert normalize.depuis_tvmaze({"id": 1, "premiere": "1999-01-10"})["annee"] == 1999
    assert "annee" not in normalize.depuis_tvmaze({"id": 1, "premiere": "????"})


def test_wikidata_livre_produit_les_faits_attendus():
    canonique = normalize.depuis_wikidata_livre(WIKIDATA_LIVRE_COMPLET)

    assert canonique == {
        "annee": 1967,
        "pays": ["CO"],
        "langues": ["es"],
        "auteurs": [{"qid": "Q5878", "nom": "Gabriel García Márquez"}],
        "ids": {"wikidata": "Q189378", "openlibrary": "OL27258W"},
    }


def test_openlibrary_produit_les_faits_attendus():
    canonique = normalize.depuis_openlibrary(OPENLIBRARY_WORK, OPENLIBRARY_EDITIONS)

    assert canonique == {
        "titre": "Cien años de soledad",
        "editions": {
            "par_langue": OPENLIBRARY_EDITIONS["editions"],
            "total": 64,
            "sans_langue": 15,
            "tronque": False,
        },
        "ids": {"openlibrary": "OL27258W"},
    }


def test_openlibrary_sans_editions_reste_sans_cle():
    """Un work trouvé mais sans inventaire d'éditions (réponse en échec) ne
    fabrique pas une clé `editions` vide."""
    canonique = normalize.depuis_openlibrary(OPENLIBRARY_WORK, None)

    assert "editions" not in canonique
