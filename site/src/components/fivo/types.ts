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

export interface Suggestion {
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
