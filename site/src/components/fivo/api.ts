// Le client HTTP du composant. Toujours la même origine : en dev Astro
// relaie /api vers le service webapp (astro.config.mjs), en production c'est
// le service qui sert le site — le cookie de session reste propriétaire.

import type { Carte, Compte, Episode, Fiche, FichePersonne, Filtres, Five, FiveCommunaute, ListeFive, Signal, Statut, Suggestion, UniversSlug } from './types'

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
  options: {
    /** Les genres masqués (« moins de dessins animés ») — répétés en `sans=`. */
    sans?: string[]
    /** Les plateformes choisies (« sur Netflix ») — répétées en `sur=`. */
    sur?: string[]
    /** La langue : elle décide du pays dont on lit la disponibilité. */
    langue?: string
    /** La page du vivier classé — la 2 continue où la 1 s'arrête. */
    page?: number
  } = {},
): Promise<{
  items: Suggestion[]
  raison: string | null
  graine?: number
  total: number
  encore: boolean
  page: number
}> {
  const params = new URLSearchParams({ univers })
  for (const genre of options.sans ?? []) params.append('sans', genre)
  for (const plateforme of options.sur ?? []) params.append('sur', plateforme)
  if (options.langue) params.set('langue', options.langue)
  if (options.page && options.page > 1) params.set('page', String(options.page))
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

// --- Le compte et les fives -------------------------------------------------

export function obtenirCompte(): Promise<{ compte: Compte | null }> {
  return requete('/compte')
}

export function inscrire(donnees: {
  pseudo: string
  email: string
  motDePasse: string
  genre?: string | null
  langue?: string
}): Promise<{ envoye: boolean; email: string }> {
  return requete('/compte/inscrire', { method: 'POST', body: JSON.stringify(donnees) })
}

export function verifierCode(email: string, code: string): Promise<{ compte: Compte }> {
  return requete('/compte/verifier', { method: 'POST', body: JSON.stringify({ email, code }) })
}

export function connecter(
  email: string,
  motDePasse: string,
  langue?: string,
): Promise<{ compte?: Compte; verificationRequise?: boolean; email?: string }> {
  return requete('/compte/connecter', {
    method: 'POST',
    body: JSON.stringify({ email, motDePasse, langue }),
  })
}

export function renvoyerCode(email: string, langue?: string): Promise<{ envoye: boolean }> {
  return requete('/compte/renvoyer', { method: 'POST', body: JSON.stringify({ email, langue }) })
}

export function deconnecter(): Promise<{ deconnecte: boolean }> {
  return requete('/compte/deconnecter', { method: 'POST' })
}

export function chargerFives(
  univers: UniversSlug,
  liste: ListeFive = 'vie',
): Promise<{ items: Five[]; rangs: number[] }> {
  return requete(`/fives?univers=${univers}&liste=${liste}`)
}

export function poserFive(
  univers: UniversSlug,
  liste: ListeFive,
  rang: number,
  oeuvreId: number,
): Promise<{ pose: boolean }> {
  return requete('/fives', {
    method: 'POST',
    body: JSON.stringify({ univers, liste, rang, oeuvreId }),
  })
}

export function retirerFive(
  univers: UniversSlug,
  liste: ListeFive,
  rang: number,
): Promise<{ retire: boolean }> {
  return requete(`/fives/${univers}/${liste}/${rang}`, { method: 'DELETE' })
}

export function fivesCommunaute(univers: UniversSlug): Promise<{ items: FiveCommunaute[] }> {
  return requete(`/fives/communaute?univers=${univers}`)
}

export function modifierCompte(profil: {
  pseudo?: string
  avatar?: string
  genre?: string
}): Promise<{ compte: Compte }> {
  return requete('/compte', { method: 'PATCH', body: JSON.stringify(profil) })
}
