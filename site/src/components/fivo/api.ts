// Le client HTTP du composant. Toujours la même origine : en dev Astro
// relaie /api vers le service webapp (astro.config.mjs), en production c'est
// le service qui sert le site — le cookie de session reste propriétaire.

import type { Carte, Signal, Statut, Suggestion, UniversSlug } from './types'

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

export function rechercher(
  univers: UniversSlug,
  q: string,
  signal?: AbortSignal,
): Promise<{ items: Carte[]; moteur: string }> {
  const params = new URLSearchParams({ univers, q })
  return requete(`/recherche?${params}`, { signal })
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
 *  complète (couvertures Open Library des livres) passe telle quelle. */
export function urlAffiche(affiche: string | null): string | null {
  if (!affiche) return null
  return affiche.startsWith('http') ? affiche : `https://image.tmdb.org/t/p/w185${affiche}`
}
