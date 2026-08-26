// Les formes que l'API publique rend — le miroir TypeScript de
// webapp/src/fiv_webapp (cartes.py, signaux.py, suggestions.py).

export type UniversSlug = 'series' | 'films' | 'livres'

export type Statut = 'aime' | 'aime_pas' | 'a_voir'

export interface Carte {
  /** La clé de la vignette : id TMDB pour séries et films, pivot pour les livres. */
  id: number
  /** Le pivot `sourcing.oeuvre.id` — l'identité que le classement manipule.
   *  Null si l'œuvre n'a pas encore de pivot : les boutons sont alors inertes. */
  oeuvreId: number | null
  univers: UniversSlug
  titre: string | null
  titreOriginal: string | null
  annee: number | null
  affiche: string | null
  synopsis: string | null
  genres: string[]
  note: number | null
}

export interface Signal {
  oeuvreId: number
  univers: string
  statut: Statut
  titre: string | null
  affiche: string | null
  annee: number | null
}

/** Une valeur de filtre et son nombre d'œuvres. */
export interface Facette {
  valeur: string
  nombre: number
}

/** Une dimension de filtre et ses valeurs. Le front n'en connaît aucune
 *  d'avance : il affiche les groupes qu'on lui répond, libellés compris — les
 *  séries et les films portent genres ET plateformes, un livre ne se regarde
 *  pas sur Netflix. */
export interface GroupeFiltre {
  champ: string
  libelle: string
  valeurs: Facette[]
}

export interface Filtres {
  langue: string
  groupes: GroupeFiltre[]
}

/** Une plateforme de diffusion, telle que JustWatch la rend via TMDB. */
export interface Plateforme {
  nom: string
  logo: string | null
}

/** Une façon de regarder l'œuvre, et qui la propose. */
export interface Offre {
  genre: string
  libelle: string
  plateformes: Plateforme[]
}

/** Une bande-annonce ou un extrait. `url` et `vignette` sont fabriquées par
 *  le serveur : lui seul sait quels sites il sait adresser. */
export interface Video {
  site: string
  cle: string
  type: string
  nom: string | null
  langue: string | null
  officielle: boolean
  saison: number | null
  url: string | null
  vignette: string | null
}

export interface Personne {
  nom: string
  /** Son identité dans le graphe — `tmdb:1234`, `wd:Q535`. Nulle quand la
   *  source ne l'a pas donnée : la personne s'affiche alors sans être
   *  cliquable, plutôt que d'ouvrir la filmographie d'un homonyme. */
  cle: string | null
  /** Le personnage joué, « Création », « Réalisation » ou « Auteur ». */
  role: string | null
  photo: string | null
  episodes: number | null
}

export interface Episode {
  numero: number
  titre: string | null
  synopsis: string | null
  diffusion: string | null
  duree: number | null
  image: string | null
  note: number | null
}

export interface Saison {
  numero: number
  nom: string | null
  annee: number | null
  episodes: number | null
  affiche: string | null
  synopsis: string | null
}

/** L'œuvre en grand — ce que la modale affiche. Un livre a les mêmes clés,
 *  ses saisons et sa distribution étant simplement vides. */
export interface Fiche {
  id: number
  oeuvreId: number | null
  univers: UniversSlug
  titre: string | null
  titreOriginal: string | null
  accroche: string | null
  annee: number | null
  synopsis: string | null
  affiche: string | null
  fond: string | null
  genres: string[]
  note: number | null
  votes: number | null
  statut: string | null
  pays: string[]
  langue: string | null
  saisonsTotal: number | null
  episodesTotal: number | null
  distribution: Personne[]
  realisation: Personne[]
  saisons: Saison[]
  /** Où regarder, dans le pays de la langue demandée. */
  offres: Offre[]
  /** Le lien JustWatch du pays — TMDB impose de citer la source. */
  lienOffres: string | null
  /** Les pays où l'œuvre est disponible : de quoi distinguer « rien chez
   *  vous » de « aucune donnée ». */
  paysOffres: string[]
  videos: Video[]
}

/** Une œuvre de la filmographie de quelqu'un. */
export interface OeuvreDePersonne {
  id: number
  oeuvreId: number
  univers: UniversSlug
  titre: string | null
  annee: number | null
  affiche: string | null
  role: string | null
}

/** Quelqu'un, sa photo, et une page de ses œuvres. `source` vaut `graphe`
 *  (exact, tous univers) ou `index` (par le nom, un seul univers, homonymes
 *  confondus) — le panneau le dit, parce que ça change ce qu'on regarde. */
export interface FichePersonne {
  cle: string
  nom: string | null
  photo: string | null
  oeuvres: OeuvreDePersonne[]
  total: number
  page: number
  parPage: number
  source: 'graphe' | 'index'
}

export interface Suggestion {
  /** La clé de vignette — id TMDB, ou pivot pour un livre. Ouvre la fiche. */
  id: number
  oeuvreId: number
  titre: string | null
  annee: number | null
  affiche: string | null
  univers: UniversSlug
  /** D'où elle vient : `voisins` la communauté, `proche` l'empreinte,
   *  `affinite` les genres et les gens. Les trois n'ont pas la même force,
   *  et l'explication affichée les distingue. */
  source: 'voisins' | 'proche' | 'affinite'
  voisins: number | null
  force: number | null
  distance: number | null
  /** Les genres partagés avec les coups de cœur — l'explication de l'étage
   *  des affinités. Vide quand la correspondance s'est faite sur un nom. */
  communs: string[]
  /** Le contenu ET la communauté désignent-ils cette œuvre ? C'est la
   *  suggestion la plus solide que le moteur sache produire, et elle se dit. */
  corrobore: boolean
}

/** Le type d'une œuvre, au singulier — affiché en gras sur la carte à côté
 *  de l'année. `UNIVERS_LABELS` est le pluriel des onglets ; ce n'est pas la
 *  même chose et les confondre donnerait « 1954 · Livres ». */
export const TYPE_LABELS: Record<UniversSlug, string> = {
  series: 'Série',
  films: 'Film',
  livres: 'Livre',
}

export const UNIVERS_LABELS: Record<UniversSlug, string> = {
  series: 'Séries',
  films: 'Films',
  livres: 'Livres',
}
