"""Lecture des réponses de Wikidata, Wikipédia et TVmaze.

Pas de réseau, pas de base : ces fonctions ne font que traduire une réponse en
données utilisables. C'est là que se logent les pièges de format, donc c'est là
qu'il faut des cas nommés.
"""

from __future__ import annotations

from fiv_sourcing.sources import tvmaze, wikidata, wikipedia


# ------------------------------------------------------------------ wikidata
def _binding(**champs: str) -> dict:
    return {"results": {"bindings": [{k: {"value": v} for k, v in champs.items()}]}}


def test_lookup_aplatit_les_listes_concatenees():
    faits = wikidata.lire_lookup(
        _binding(
            item="http://www.wikidata.org/entity/Q23572",
            imdb="tt0944947",
            tvmaze="82",
            pays="US|GB",
            tournage="Belfast|Dubrovnik",
        )
    )

    assert faits["qid"] == "Q23572"
    assert faits["imdb"] == "tt0944947"
    assert faits["pays"] == ["US", "GB"]
    assert faits["lieux_tournage"] == ["Belfast", "Dubrovnik"]
    assert faits["lieux_action"] == []


def test_lookup_sans_resultat_vaut_none():
    """Le cas majoritaire au fond du catalogue : la série n'est pas dans
    Wikidata. Ce n'est pas une erreur, c'est une absence."""
    assert wikidata.lire_lookup({"results": {"bindings": []}}) is None
    assert wikidata.lire_lookup(None) is None


def test_les_champs_optionnels_absents_ne_font_pas_echouer():
    faits = wikidata.lire_lookup(_binding(item="http://www.wikidata.org/entity/Q1"))
    assert faits == {
        "qid": "Q1",
        "imdb": None,
        "tvmaze": None,
        "pays": [],
        "langues": [],
        "lieux_tournage": [],
        "lieux_action": [],
    }


def test_seules_les_wikipedias_sont_retenues():
    """`sitelinks` mélange tous les projets Wikimedia. Prendre wikiquote pour
    un article donnerait un texte de citations là où on attend une intrigue."""
    articles = wikidata.lire_sitelinks(
        {
            "entities": {
                "Q23572": {
                    "sitelinks": {
                        "frwiki": {"title": "Le Trône de fer"},
                        "enwiki": {"title": "Game of Thrones"},
                        "frwikiquote": {"title": "Citations"},
                        "commonswiki": {"title": "Category:GoT"},
                    }
                }
            }
        },
        "Q23572",
    )

    assert articles == {"fr": "Le Trône de fer", "en": "Game of Thrones"}


# ----------------------------------------------------------------- wikipédia
def test_l_article_est_lu_en_entier():
    lu = wikipedia.lire_article(
        {"query": {"pages": [{"title": "Le Trône de fer", "extract": "Un très long texte."}]}}
    )
    assert lu == ("Le Trône de fer", "Un très long texte.")


def test_une_page_absente_vaut_none():
    assert wikipedia.lire_article({"query": {"pages": [{"title": "X", "missing": True}]}}) is None
    assert wikipedia.lire_article({"query": {"pages": [{"title": "X", "extract": "  "}]}}) is None


# -------------------------------------------------------------------- tvmaze
def _candidat(show_id: int, imdb: str | None) -> dict:
    return {"show": {"id": show_id, "externals": {"imdb": imdb} if imdb else {}}}


def test_l_appariement_se_decide_sur_l_imdb_pas_sur_le_rang():
    """Mesuré sur 64 paires : le bon candidat n'est pas toujours en tête, et le
    premier peut être un homonyme (deux séries s'appellent Teen Wolf)."""
    resultats = [_candidat(1, "tt111"), _candidat(2, "tt222")]
    assert tvmaze.choisir_par_titre(resultats, "tt222") == 2


def test_sans_imdb_aucun_appariement_n_est_accepte():
    """Une ligne fausse coûte plus qu'une ligne absente : elle ne se signale
    pas."""
    assert tvmaze.choisir_par_titre([_candidat(1, "tt111")], None) is None
    assert tvmaze.choisir_par_titre([_candidat(1, None)], "tt111") is None
    assert tvmaze.choisir_par_titre(None, "tt111") is None


def test_les_resumes_d_episode_sont_concatenes_sans_balises():
    lu = tvmaze.lire_show(
        {
            "id": 82,
            "name": "Game of Thrones",
            "network": {"name": "HBO", "country": {"code": "US"}},
            "_embedded": {
                "episodes": [
                    {"airdate": "2011-04-17", "summary": "<p>Ned <b>Stark</b> part.</p>"},
                    {"airdate": "2011-04-24", "summary": None},
                    {"airdate": None, "summary": "<p>Tyrion &amp; Jaime.</p>"},
                ]
            },
        }
    )

    assert lu["episodes"] == 3
    assert lu["episodes_dates"] == 2
    assert lu["diffuseur"] == "HBO"
    assert lu["pays"] == "US"
    assert lu["texte"] == "Ned Stark part.\n\nTyrion & Jaime."


def test_une_serie_sans_resume_ne_donne_pas_de_texte():
    """Deux séries trouvées sur trois sont dans ce cas. `content` doit valoir
    null, pas une chaîne vide : `content_chars` compte 0 dans les deux cas mais
    la distinction « rien reçu » / « reçu vide » se perdrait."""
    lu = tvmaze.lire_show({"id": 1, "_embedded": {"episodes": [{"summary": ""}]}})
    assert lu["texte"] is None


def test_le_diffuseur_web_remplace_le_reseau():
    lu = tvmaze.lire_show({"id": 1, "webChannel": {"name": "Netflix"}, "_embedded": {}})
    assert lu["diffuseur"] == "Netflix"


def test_l_affiche_est_prise_a_defaut_en_taille_moyenne():
    assert tvmaze.images({"image": {"medium": "http://x/m.jpg"}}) == [
        {"type": "poster", "url": "http://x/m.jpg"}
    ]
    assert tvmaze.images({"image": None}) == []


def test_les_group_concat_sont_canonicalises():
    """Blazegraph ne garantit pas l'ordre des GROUP_CONCAT : deux réponses au
    même contenu peuvent différer par une permutation. Constaté en vrai — une
    ligne de brut en plus à chaque rejeu, en violation de R2."""
    payload = {
        "results": {
            "bindings": [
                {
                    "tournage": {"value": "Malta|Croatia|Morocco"},
                    "pays": {"value": "US|GB"},
                    "imdb": {"value": "tt1"},
                }
            ]
        }
    }

    wikidata.canonicaliser(payload)
    ligne = payload["results"]["bindings"][0]

    assert ligne["tournage"]["value"] == "Croatia|Malta|Morocco"
    assert ligne["pays"]["value"] == "GB|US"
    assert ligne["imdb"]["value"] == "tt1", "les champs non agrégés ne bougent pas"


def test_canonicaliser_est_idempotent():
    payload = {"results": {"bindings": [{"pays": {"value": "GB|US"}}]}}
    assert wikidata.canonicaliser(wikidata.canonicaliser(payload)) == {
        "results": {"bindings": [{"pays": {"value": "GB|US"}}]}
    }
