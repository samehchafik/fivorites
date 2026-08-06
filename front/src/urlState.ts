/**
 * L'état partageable, porté par l'URL.
 *
 * Deux choses seulement y figurent, parce que ce sont les deux qu'on a besoin
 * d'envoyer à quelqu'un : la fiche ouverte et les filtres actifs.
 *
 *     ?id=1399
 *     ?filtre=image,description
 *     ?id=1399&filtre=description
 *
 * Le sens de la lecture compte : **l'URL est la source**, l'état de
 * l'application en découle au chargement, puis la réécrit. Une URL collée dans
 * une conversation rouvre donc exactement la même vue — y compris les cases
 * cochées, pas seulement le résultat filtré.
 *
 * `replaceState` et non `pushState` : cocher une case n'est pas une navigation,
 * et empiler une entrée d'historique par clic rendrait le bouton « précédent »
 * inutilisable. La contrepartie assumée est que « précédent » ne referme pas la
 * fiche — il n'y a pas de routeur dans cette application, et il n'y en avait
 * déjà pas avant.
 */

/** Les noms lisibles des filtres, tels qu'on les écrit dans l'URL.
 *
 *  `image` et `description` plutôt que `withPoster` et `withOverview` : une URL
 *  se lit et se tape à la main, et se retrouve dans un ticket. */
const FILTRES = {
  image: 'withPoster',
  description: 'withOverview',
} as const

export interface UrlState {
  /** La fiche à ouvrir, ou null. */
  id: number | null
  withPoster: boolean
  withOverview: boolean
}

export function readUrl(search = window.location.search): UrlState {
  const params = new URLSearchParams(search)

  const brut = params.get('id')
  const id = brut === null ? Number.NaN : Number(brut)

  // Un `id` qui n'est pas un entier positif est ignoré plutôt que transmis :
  // `?id=abc` ouvrirait une fiche « NaN » et l'API répondrait par une erreur de
  // validation, là où ne rien ouvrir est le comportement attendu.
  const actifs = (params.get('filtre') ?? '')
    .split(',')
    .map((nom) => nom.trim())
    .filter(Boolean)

  return {
    id: Number.isInteger(id) && id > 0 ? id : null,
    withPoster: actifs.includes('image'),
    withOverview: actifs.includes('description'),
  }
}

export function writeUrl(state: UrlState, replace = true): void {
  // On repart des paramètres existants : ceux qu'on ne connaît pas — un
  // `?utm_source`, un futur `?lang` — n'ont pas à disparaître parce qu'on a
  // coché une case.
  const params = new URLSearchParams(window.location.search)

  if (state.id !== null) params.set('id', String(state.id))
  else params.delete('id')

  const filtres = (Object.keys(FILTRES) as (keyof typeof FILTRES)[]).filter(
    (nom) => state[FILTRES[nom]],
  )
  if (filtres.length > 0) params.set('filtre', filtres.join(','))
  else params.delete('filtre')

  // `URLSearchParams` encode la virgule en `%2C`. Elle est pourtant légale
  // telle quelle dans une chaîne de requête (RFC 3986, sous-délimiteur), et
  // `?filtre=image,description` se lit et se retape, contrairement à
  // `?filtre=image%2Cdescription`. On la remet en clair : c'est la même URL
  // pour le serveur, une URL utilisable pour un humain.
  const query = params.toString().replace(/%2C/g, ',')
  const url = query ? `${window.location.pathname}?${query}` : window.location.pathname

  // Rien à faire si l'URL ne change pas : `replaceState` à chaque rendu
  // encombrerait les outils de développement sans aucun effet visible.
  if (url === window.location.pathname + window.location.search) return
  if (replace) window.history.replaceState(null, '', url)
  else window.history.pushState(null, '', url)
}
