"""Les univers de collecte, et ce qui change de l'un à l'autre.

Un univers n'est pas une commande, c'est un paramètre : `tmdb export` fait la
même chose pour les films et pour les séries, à quatre détails près que ce
fichier énumère. Les dupliquer en `tmdb export-films` reviendrait à maintenir
deux fois la même logique de repli de date, de COPY et d'upsert — et à les
laisser diverger.

Les quatre détails, mesurés sur les deux exports et les deux endpoints :

* le **nom du fichier d'export** : `tv_series_ids` contre `movie_ids` ;
* le **champ de titre** que ce fichier porte : `original_name` contre
  `original_title` — TMDB n'a jamais unifié les deux vocabulaires ;
* le **segment d'URL** de l'API : `/tv/{id}` contre `/movie/{id}`, qui est
  aussi le `kind` sous lequel le brut se range ;
* la **présence de parties** : une série se collecte saison par saison et dans
  cinq langues, un film tient en un appel. C'est l'écart de coût dominant —
  environ 40 requêtes contre une.

L'enrichissement en ajoute trois, du même genre :

* la **propriété Wikidata** qui porte l'identifiant TMDB : `P4983` contre
  `P4947`. Les deux catalogues se numérotent indépendamment, et entrer par la
  mauvaise ramènerait l'œuvre homonyme sans lever d'erreur ;
* **TVmaze**, qui est une base de séries et n'a rien à dire d'un film ;
* le **`kind` de reprise** dans `fetch_state`, pour que le film 550 et la série
  550 ne se volent pas leur état de passage.

Ce que ce fichier ne dit pas, volontairement : les sous-requêtes
`append_to_response`, qui vivent dans `client.py` avec l'avertissement qui les
accompagne (les changer oblige à retélécharger le catalogue entier).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Univers:
    cle: str
    """`series` | `movies` — la valeur de `tmdb_catalog.univers` et de
    `oeuvre.univers`. C'est l'identité, pas l'affichage."""

    kind: str
    """`tv` | `movie` — le segment d'URL de TMDB, et le `kind` de `raw_source`.
    Les deux coïncident, et ce n'est pas un hasard : le brut se range sous le
    nom de l'endpoint qui l'a servi."""

    export: str
    """Le préfixe du fichier d'export quotidien."""

    titre_export: str
    """Le champ de titre dans ce fichier."""

    date_fiche: str
    """Le champ de date de la fiche : `first_air_date` ou `release_date`. Les
    deux atterrissent dans la colonne `tmdb_catalog.first_air_date`, qui garde
    son nom — la renommer toucherait la projection de l'admin et tout le front
    pour un gain d'esthétique."""

    parties: bool
    """La collecte descend-elle dans des sous-objets (les saisons) ?"""

    part_kind: str | None
    """Le `kind` de ces sous-objets dans `raw_source`, s'il y en a."""

    libelle: str
    """Pour les messages de la ligne de commande, au singulier."""

    wikidata_propriete: str
    """La propriété Wikidata qui porte l'identifiant TMDB. `P4983` pour les
    séries, `P4947` pour les films — Wikidata les sépare parce que les deux
    catalogues TMDB se numérotent indépendamment. Entrer par la mauvaise
    ramènerait l'œuvre qui porte le même numéro dans l'autre catalogue, sans
    lever la moindre erreur."""

    tvmaze: bool
    """TVmaze est une base de séries. Interroger pour un film ferait une requête
    par œuvre pour ne jamais rien trouver."""

    lookup_kind: str
    """Le `kind` sous lequel `fetch_state` note le passage Wikidata. Il diffère
    d'un univers à l'autre pour la même raison que tout le reste : la clé de
    reprise est l'identifiant TMDB, et le film 550 partagerait sinon l'état du
    passage de la série 550 — l'un empêcherait l'autre d'être tenté."""


SERIES = Univers(
    cle="series",
    kind="tv",
    export="tv_series_ids",
    titre_export="original_name",
    date_fiche="first_air_date",
    parties=True,
    part_kind="tv_season",
    libelle="série",
    wikidata_propriete="P4983",
    tvmaze=True,
    lookup_kind="lookup",
)

FILMS = Univers(
    cle="movies",
    kind="movie",
    export="movie_ids",
    titre_export="original_title",
    date_fiche="release_date",
    parties=False,
    part_kind=None,
    libelle="film",
    wikidata_propriete="P4947",
    tvmaze=False,
    lookup_kind="lookup_movie",
)

UNIVERS: dict[str, Univers] = {u.cle: u for u in (SERIES, FILMS)}

DEFAUT = SERIES


def resoudre(cle: str | None) -> Univers:
    """`'movies'` → l'univers des films. Liste fermée : la valeur vient de la
    ligne de commande, et une faute de frappe doit s'arrêter ici plutôt que de
    créer un troisième univers silencieux dans `tmdb_catalog`."""
    if not cle:
        return DEFAUT
    if cle not in UNIVERS:
        attendus = ", ".join(UNIVERS)
        raise ValueError(f"univers inconnu : {cle} (attendus : {attendus})")
    return UNIVERS[cle]


def kinds_de(univers: Univers) -> tuple[str, ...]:
    """Tous les `kind` de `raw_source` que cet univers alimente.

    Une série en occupe deux — sa fiche et ses saisons — et les deux comptent
    quand on mesure ce qu'elle pèse sur le disque.
    """
    return (univers.kind,) if univers.part_kind is None else (univers.kind, univers.part_kind)
