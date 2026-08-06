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
    ids                 {"tmdb": int, "imdb": str, "wikidata": str, "tvmaze": int}
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
