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

/** Ce sur quoi cet univers se filtre. La dimension varie — genres pour les
 *  séries et les films, langues pour les livres, qui n'ont aucun genre en
 *  base — et le front n'en sait rien d'avance : il affiche ce qu'on lui
 *  répond, libellé compris. */
export interface Filtres {
  dimension: string
  libelle: string
  valeurs: Facette[]
}

export interface Personne {
  nom: string
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
