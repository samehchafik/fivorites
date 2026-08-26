"""Les trois univers du site public, et comment on les lit.

Le registre est le pendant public de `fiv_admin.media.MEDIA`, réduit à ce que
le site consomme : la vue de vignettes, l'alias Elasticsearch, et la colonne
sur laquelle joindre le pivot. Les clés sont les slugs PUBLICS — `series`,
`films`, `livres` — ceux des URL et du composant de suggestion : le
vocabulaire interne (`movies`, `tv`) ne sort pas du serveur.

Ce qu'un univers doit fournir pour être servi : une projection de vignettes
aux colonnes de `admin.tv_card`, et un alias `catalog-<univers>` chez ES.
`bd` et `musiques` entreront ici le jour où leur collecte existe — et nulle
part ailleurs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Univers:
    # Le slug public — celui des URL du site et des appels d'API.
    slug: str
    label: str
    # La valeur de `sourcing.oeuvre.univers`, et le second label des nœuds du
    # graphe (`FivSerie`, `FivFilm`, `FivLivre` en découlent côté admin).
    interne: str
    # La projection de vignettes, dans le schéma `admin`.
    card_view: str
    # Les vignettes sont keyées par le pivot `sourcing.oeuvre.id` plutôt que
    # par un identifiant TMDB. Vrai pour les livres — il n'y a pas de TMDB du
    # livre : la jointure d'identité suit ce drapeau.
    pivot_card: bool = False
    # Sur quoi cet univers se filtre, et sous quel nom l'annoncer.
    #
    # Ce n'est pas la même dimension partout, et ça ne peut pas l'être : les
    # séries et les films portent les genres de TMDB, les livres n'en ont
    # AUCUN — l'enrichissement Wikidata ne rend que des auteurs, des langues,
    # des pays et une année (vérifié en base). Leur proposer une liste de
    # genres vide serait un filtre en trompe-l'œil ; on leur propose la
    # langue, qui est la donnée que cet univers existe pour porter.
    #
    # Le jour où le crawler collectera P136 (le genre littéraire de Wikidata),
    # les livres basculeront sur `genres` en changeant ces deux lignes.
    champ_filtre: str = "genres"
    label_filtre: str = "Genres"

    @property
    def alias_recherche(self) -> str:
        """L'alias Elasticsearch — le même que `fiv_admin.search.alias_de`."""
        return f"catalog-{self.interne}"


UNIVERS: dict[str, Univers] = {
    "series": Univers(slug="series", label="Séries", interne="series", card_view="tv_card"),
    "films": Univers(slug="films", label="Films", interne="movies", card_view="movie_card"),
    "livres": Univers(
        slug="livres",
        label="Livres",
        interne="livres",
        card_view="livre_card",
        pivot_card=True,
        champ_filtre="langues",
        label_filtre="Langues",
    ),
}


def univers_ou_400(slug: str) -> Univers:
    """L'univers demandé, ou l'erreur qui dit lesquels existent.

    Levée en `ValueError` plutôt qu'en `HTTPException` : ce module ne connaît
    pas FastAPI, et c'est aux routes de traduire — elles seules savent qu'un
    univers inconnu est un 400.
    """
    univers = UNIVERS.get(slug)
    if univers is None:
        raise ValueError(f"univers inconnu : {slug} (attendu : {', '.join(UNIVERS)})")
    return univers
