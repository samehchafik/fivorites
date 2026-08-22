"""Le JSON canonique des `facts` — R5 de l'architecture cible.

Un seul schéma, quelles que soient la source et la série. Ce module est la
**seule frontière** entre les formats propriétaires (Wikidata, TVmaze, demain
d'autres) et le reste du projet : personne d'autre ne lit un champ propriétaire.

Deux règles, tenues par les tests :

  * une clé sans valeur est **absente**, jamais inventée — pas de null, pas de
    liste vide de remplissage ;
  * aucune clé hors du schéma. Une source qui apporte une donnée nouvelle passe
    par ici, ou la donnée n'existe pas.

Le schéma (doc/architecture-sourcing.md §3) :

    titre               str
    titres_alternatifs  [str]
    annee               int
    statut              en_cours | terminee | annulee
    pays                [str]  codes ISO
    langues             [str]  codes ISO
    lieux               [{"type": tournage|action, "nom": str}]
    diffuseur           str
    calendrier          {"jours": [str], "heure": str}
    episodes            {"total": int, "dates": int, "resumes": int}
    auteurs             [{"qid": str?, "nom": str?}]   (livres)
    sitelinks           int   (livres) — le proxy de notoriété
    editions            {"par_langue": [{"langue", "nombre", "isbn"?, "annee"?}],
                         "total": int, "sans_langue": int, "tronque": bool}   (livres)
    ids                 {"tmdb": int, "imdb": str, "wikidata": str, "tvmaze": int,
                         "openlibrary": str}

Les deux clés livres suivent la même règle que `episodes` ou `calendrier` :
elles n'existent que pour l'univers qui les porte, jamais en remplissage.
`editions.par_langue` est un résumé, pas un inventaire — une entrée par
langue, un ISBN représentatif, la première année : c'est ce que la couche 1
et le lien d'achat consomment. L'inventaire complet reste chez Open Library,
réinterrogeable (R4).
"""

from __future__ import annotations

from typing import Any

CLES = frozenset(
    {
        "titre",
        "titres_alternatifs",
        "annee",
        "statut",
        "pays",
        "langues",
        "lieux",
        "diffuseur",
        "calendrier",
        "episodes",
        "auteurs",
        "sitelinks",
        "editions",
        "ids",
    }
)

# TVmaze est la seule source à porter un statut. Les valeurs non listées —
# « To Be Determined », « In Development » — ne sont pas un statut de diffusion
# mais une incertitude : la clé reste absente.
_STATUTS_TVMAZE = {
    "Running": "en_cours",
    "Ended": "terminee",
    "Canceled": "annulee",
    "Cancelled": "annulee",
}


def depuis_wikidata(faits: dict[str, Any]) -> dict[str, Any]:
    """Depuis la sortie de `wikidata.lire_lookup`."""
    canonique: dict[str, Any] = {}

    _si(canonique, "pays", list(faits.get("pays") or []))
    _si(canonique, "langues", list(faits.get("langues") or []))

    lieux = [{"type": "tournage", "nom": nom} for nom in faits.get("lieux_tournage") or []]
    lieux += [{"type": "action", "nom": nom} for nom in faits.get("lieux_action") or []]
    _si(canonique, "lieux", lieux)

    ids: dict[str, Any] = {}
    _si(ids, "wikidata", faits.get("qid"))
    _si(ids, "imdb", faits.get("imdb"))
    _si(ids, "tvmaze", _entier(faits.get("tvmaze")))
    _si(canonique, "ids", ids)

    return canonique


def depuis_wikidata_livre(faits: dict[str, Any]) -> dict[str, Any]:
    """Depuis la sortie de `wikidata.lire_lookup_livre`.

    `langues` porte la langue d'origine (P407) — la même clé que pour une
    série (P364) : la propriété diffère, le fait canonique est le même.
    """
    canonique: dict[str, Any] = {}

    _si(canonique, "annee", faits.get("annee"))
    _si(canonique, "pays", list(faits.get("pays") or []))
    _si(canonique, "langues", list(faits.get("langues") or []))
    # Le nombre de Wikipédias qui portent l'œuvre. Les autres univers tiennent
    # leur popularité de l'export TMDB (`tmdb_catalog.popularity`) ; les livres
    # n'ont pas d'inventaire, et c'est donc un fait de la source — le seul
    # proxy de notoriété gratuit, celui par lequel le balayage classe déjà.
    _si(canonique, "sitelinks", faits.get("sitelinks"))

    auteurs = []
    for auteur in faits.get("auteurs") or []:
        forme: dict[str, Any] = {}
        _si(forme, "qid", auteur.get("qid"))
        _si(forme, "nom", auteur.get("nom"))
        if forme:
            auteurs.append(forme)
    _si(canonique, "auteurs", auteurs)

    ids: dict[str, Any] = {}
    _si(ids, "wikidata", faits.get("qid"))
    _si(ids, "openlibrary", faits.get("olid"))
    _si(canonique, "ids", ids)

    return canonique


def depuis_openlibrary(work: dict[str, Any], editions: dict[str, Any] | None) -> dict[str, Any]:
    """Depuis les sorties de `openlibrary.lire_work` et `lire_editions`."""
    canonique: dict[str, Any] = {}

    _si(canonique, "titre", work.get("titre"))

    if editions and editions.get("total"):
        canonique["editions"] = {
            "par_langue": editions.get("editions") or [],
            "total": editions["total"],
            "sans_langue": editions.get("sans_langue", 0),
            "tronque": bool(editions.get("tronque")),
        }

    ids: dict[str, Any] = {}
    _si(ids, "openlibrary", work.get("olid"))
    _si(canonique, "ids", ids)

    return canonique


def depuis_tvmaze(lu: dict[str, Any]) -> dict[str, Any]:
    """Depuis la sortie de `tvmaze.lire_show`."""
    canonique: dict[str, Any] = {}

    _si(canonique, "titre", lu.get("nom"))
    _si(canonique, "annee", _annee(lu.get("premiere")))
    _si(canonique, "statut", _STATUTS_TVMAZE.get(lu.get("statut") or ""))
    _si(canonique, "pays", [lu["pays"]] if lu.get("pays") else [])
    _si(canonique, "diffuseur", lu.get("diffuseur"))

    brut = lu.get("calendrier") or {}
    calendrier: dict[str, Any] = {}
    _si(calendrier, "jours", list(brut.get("days") or []))
    _si(calendrier, "heure", brut.get("time"))
    _si(canonique, "calendrier", calendrier)

    episodes: dict[str, Any] = {}
    if lu.get("episodes"):
        episodes["total"] = lu["episodes"]
        _si(episodes, "dates", lu.get("episodes_dates"))
        _si(episodes, "resumes", lu.get("episodes_resumes"))
    _si(canonique, "episodes", episodes)

    ids: dict[str, Any] = {}
    _si(ids, "tvmaze", _entier(lu.get("id")))
    _si(ids, "imdb", lu.get("imdb"))
    _si(canonique, "ids", ids)

    return canonique


def _si(cible: dict[str, Any], cle: str, valeur: Any) -> None:
    """Pose la clé seulement si la valeur porte quelque chose."""
    if valeur or valeur == 0:
        cible[cle] = valeur


def _annee(date_iso: str | None) -> int | None:
    if not date_iso or len(date_iso) < 4 or not date_iso[:4].isdigit():
        return None
    return int(date_iso[:4])


def _entier(valeur: Any) -> int | None:
    try:
        return int(valeur) if valeur is not None else None
    except (TypeError, ValueError):
        return None
