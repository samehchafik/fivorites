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


@pytest.mark.parametrize(
    "canonique",
    [
        normalize.depuis_wikidata(WIKIDATA_COMPLET),
        normalize.depuis_tvmaze(TVMAZE_COMPLET),
    ],
    ids=["wikidata", "tvmaze"],
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
