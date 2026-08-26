// Le client HTTP du composant. Toujours la même origine : en dev Astro
// relaie /api vers le service webapp (astro.config.mjs), en production c'est
// le service qui sert le site — le cookie de session reste propriétaire.

import type {
  Carte,
  Episode,
  Fiche,
  FichePersonne,
  Filtres,
  Signal,
  Statut,
  Suggestion,
  UniversSlug,
} from './types'

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
  options: {
    page?: number
    /** Les valeurs cochées, par dimension : `{genres: [...], plateformes: [...]}`.
     *  Les dimensions viennent de `/filtres` — rien n'est en dur ici. */
    filtres?: Record<string, string[]>
    /** La langue de qui cherche — sans elle, la liste mélange les langues. */
    langue?: string
    signal?: AbortSignal
  } = {},
): Promise<PageRecherche> {
  const params = new URLSearchParams({ univers, q })
  if (options.page && options.page > 1) params.set('page', String(options.page))
  if (options.langue) params.set('langue', options.langue)
  // Répété plutôt que joint : une valeur peut contenir une virgule, et
  // FastAPI lit nativement la forme répétée. Un paramètre par dimension.
  for (const [champ, valeurs] of Object.entries(options.filtres ?? {})) {
    for (const valeur of valeurs) params.append(champ, valeur)
  }
  return requete(`/recherche?${params}`, { signal: options.signal })
}

/** Quelqu'un et une page de sa filmographie.
 *
 *  `univers` et `nom` ne servent qu'au repli : sans graphe projeté, le
 *  serveur ne sait chercher que par le nom, dans un seul univers. Les passer
 *  ne coûte rien et évite un panneau vide. */
export function chargerPersonne(
  cle: string,
  options: { page?: number; univers?: UniversSlug; nom?: string } = {},
): Promise<FichePersonne> {
  const params = new URLSearchParams()
  if (options.page && options.page > 1) params.set('page', String(options.page))
  if (options.univers) params.set('univers', options.univers)
  if (options.nom) params.set('nom', options.nom)
  return requete(`/personne/${encodeURIComponent(cle)}?${params}`)
}

/** Les groupes de filtres de cet univers. La langue compte : les plateformes
 *  sont indexées par pays, et « Netflix » en France n'est pas « Shahid » en
 *  Arabie saoudite. */
export function chargerFiltres(univers: UniversSlug, langue?: string): Promise<Filtres> {
  const params = new URLSearchParams({ univers })
  if (langue) params.set('langue', langue)
  return requete(`/filtres?${params}`)
}

/** La fiche détaillée. `identifiant` est la clé de la vignette — celle que
 *  la carte porte dans `id`, jamais le pivot. */
export function chargerFiche(
  univers: UniversSlug,
  identifiant: number,
  langue?: string,
): Promise<Fiche> {
  const params = new URLSearchParams({ univers })
  if (langue) params.set('langue', langue)
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

/** Les classements de la session.
 *
 *  Sans `langue`, les titres sont ceux des projections (français) : c'est
 *  suffisant au montage, où l'on ne relit que les statuts pour rallumer les
 *  boutons. Avec, le serveur les remplace par ceux de l'index — ce que
 *  demande « Ma liste », qui les AFFICHE. */
export function listerSignaux(langue?: string): Promise<{ items: Signal[] }> {
  return requete(`/signaux${langue ? `?langue=${encodeURIComponent(langue)}` : ''}`)
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
