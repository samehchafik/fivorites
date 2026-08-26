// Le client HTTP du composant. Toujours la même origine : en dev Astro
// relaie /api vers le service webapp (astro.config.mjs), en production c'est
// le service qui sert le site — le cookie de session reste propriétaire.

import type { Carte, Episode, Fiche, Signal, Statut, Suggestion, UniversSlug } from './types'

const BASE = '/api/public'

export class ApiErreur extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function requete<T>(chemin: string, options: RequestInit = {}): Promise<T> {
  const reponse = await fetch(`${BASE}${chemin}`, {
    credentials: 'same-origin',
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!reponse.ok) {
    throw new ApiErreur(reponse.status, await reponse.text())
  }
  return reponse.json() as Promise<T>
}

export interface PageRecherche {
  items: Carte[]
  moteur: string
  total: number
  totalApproche: boolean
  encore: boolean
  page: number
}

export function rechercher(
  univers: UniversSlug,
  q: string,
  options: { page?: number; filtres?: string[]; signal?: AbortSignal } = {},
): Promise<PageRecherche> {
  const params = new URLSearchParams({ univers, q })
  if (options.page && options.page > 1) params.set('page', String(options.page))
  // Répété plutôt que joint : un genre peut contenir une virgule (« Action &
  // Adventure » n'en a pas, mais rien ne le garantit), et FastAPI lit
  // nativement la forme répétée.
  for (const valeur of options.filtres ?? []) params.append('filtres', valeur)
  return requete(`/recherche?${params}`, { signal: options.signal })
}

/** Les filtres disponibles pour cet univers — dimension, libellé, valeurs. */
export function chargerFiltres(univers: UniversSlug): Promise<Filtres> {
  const params = new URLSearchParams({ univers })
  return requete(`/filtres?${params}`)
}

/** La fiche détaillée. `identifiant` est la clé de la vignette — celle que
 *  la carte porte dans `id`, jamais le pivot. */
export function chargerFiche(univers: UniversSlug, identifiant: number): Promise<Fiche> {
  const params = new URLSearchParams({ univers })
  return requete(`/fiche/${identifiant}?${params}`)
}

/** Les épisodes d'une saison — appelés au dépliement de l'accordéon : une
 *  série de huit saisons en porte deux cents. */
export function chargerEpisodes(
  univers: UniversSlug,
  identifiant: number,
  numero: number,
): Promise<{ episodes: Episode[] }> {
  const params = new URLSearchParams({ univers })
  return requete(`/fiche/${identifiant}/saison/${numero}?${params}`)
}

export function listerSignaux(): Promise<{ items: Signal[] }> {
  return requete('/signaux')
}

export function poserSignal(
  oeuvreId: number,
  univers: UniversSlug,
  statut: Statut,
): Promise<{ oeuvreId: number; statut: Statut }> {
  return requete('/signaux', {
    method: 'POST',
    body: JSON.stringify({ oeuvreId, univers, statut }),
  })
}

export function retirerSignal(oeuvreId: number): Promise<{ oeuvreId: number; retire: boolean }> {
  return requete(`/signaux/${oeuvreId}`, { method: 'DELETE' })
}

export function chargerSuggestions(
  univers: UniversSlug,
): Promise<{ items: Suggestion[]; raison: string | null; graine?: number }> {
  const params = new URLSearchParams({ univers })
  return requete(`/suggestions?${params}`)
}

/** L'affiche prête pour un <img> : un chemin TMDB se préfixe, une URL
 *  complète (couvertures Open Library des livres) passe telle quelle.
 *
 *  `taille` est un format TMDB (`w185` la vignette, `w342` la modale,
 *  `w780` l'image de fond, `w45` un visage) : demander la bonne évite de
 *  télécharger une affiche de 2 Mo pour une pastille de 40 pixels. */
export function urlAffiche(affiche: string | null, taille = 'w185'): string | null {
  if (!affiche) return null
  return affiche.startsWith('http') ? affiche : `https://image.tmdb.org/t/p/${taille}${affiche}`
}
