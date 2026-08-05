from __future__ import annotations

from fiv_sourcing.store import payload_digest


def test_empreinte_insensible_a_l_ordre_des_cles():
    """Le serveur ne garantit pas l'ordre des clés : deux réponses identiques
    ne doivent pas produire deux lignes dans raw_source."""
    a = {"id": 1399, "name": "Game of Thrones", "seasons": [{"n": 1}, {"n": 2}]}
    b = {"seasons": [{"n": 1}, {"n": 2}], "name": "Game of Thrones", "id": 1399}
    assert payload_digest(a) == payload_digest(b)


def test_empreinte_sensible_a_l_ordre_des_listes():
    """En revanche l'ordre d'une liste est porteur de sens (rang du casting,
    numéro de saison) : on ne le normalise pas."""
    assert payload_digest({"x": [1, 2]}) != payload_digest({"x": [2, 1]})


def test_empreinte_distingue_absence_et_valeur_nulle():
    assert payload_digest({"a": None}) != payload_digest({})


def test_empreinte_du_payload_absent():
    """Une requête en échec n'a pas de payload — il faut quand même une
    empreinte, la colonne est NOT NULL."""
    assert payload_digest(None) == payload_digest(None)
    assert payload_digest(None) != payload_digest({})
