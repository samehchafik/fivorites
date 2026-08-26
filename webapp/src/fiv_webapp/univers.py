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
class Dimension:
    """Une dimension de filtre : son nom public, son libellé, sa portée.

    Le nom public est celui de l'API et des cases à cocher (`genres`,
    `plateformes`) ; le champ de l'index peut en différer — les plateformes
    sont indexées PAR PAYS (`plateformes_fr`, `plateformes_ar`…), parce qu'une
    série sur Netflix en France est sur Shahid en Arabie saoudite et qu'un
    filtre qui répondrait la disponibilité d'ailleurs serait faux.
    """

    champ: str
    libelle: str
    # Le champ de l'index porte-t-il la langue en suffixe ?
    par_langue: bool = False

    def champ_index(self, langue: str) -> str:
        return f"{self.champ}_{langue}" if self.par_langue else self.champ


GENRES = Dimension(champ="genres", libelle="Genres")
PLATEFORMES = Dimension(champ="plateformes", libelle="Plateformes", par_langue=True)


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
    # Sur quoi cet univers se filtre. Les trois portent les genres — les
    # livres depuis que le crawler collecte P136 (migration 018), rendus à la
    # forme TMDB exprès. Les plateformes, elles, n'existent que là où TMDB
    # décrit une diffusion : un livre ne se regarde pas sur Netflix.
    dimensions: tuple[Dimension, ...] = (GENRES,)

    @property
    def alias_recherche(self) -> str:
        """L'alias Elasticsearch — le même que `fiv_admin.search.alias_de`."""
        return f"catalog-{self.interne}"

    def dimension(self, champ: str) -> Dimension | None:
        """La dimension de ce nom, si cet univers la porte. Un client qui
        filtre sur une dimension inconnue est ignoré plutôt que refusé : la
        liste des dimensions est un contrat qu'il découvre, et elle bougera."""
        return next((d for d in self.dimensions if d.champ == champ), None)


UNIVERS: dict[str, Univers] = {
    "series": Univers(
        slug="series",
        label="Séries",
        interne="series",
        card_view="tv_card",
        dimensions=(GENRES, PLATEFORMES),
    ),
    "films": Univers(
        slug="films",
        label="Films",
        interne="movies",
        card_view="movie_card",
        dimensions=(GENRES, PLATEFORMES),
    ),
    "livres": Univers(
        slug="livres",
        label="Livres",
        interne="livres",
        card_view="livre_card",
        pivot_card=True,
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
