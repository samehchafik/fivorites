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
  /** `voisins` : portée par la communauté ; `proche` : par l'empreinte. */
  source: 'voisins' | 'proche'
  voisins: number | null
  force: number | null
  distance: number | null
}

export const UNIVERS_LABELS: Record<UniversSlug, string> = {
  series: 'Séries',
  films: 'Films',
  livres: 'Livres',
}
