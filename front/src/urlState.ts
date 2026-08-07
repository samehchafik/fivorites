/**
 * L'état partageable, porté par l'URL.
 *
 * Trois choses y figurent, parce que ce sont celles qu'on a besoin d'envoyer à
 * quelqu'un : la fiche ouverte, les filtres actifs, et la langue.
 *
 *     ?id=1399
 *     ?filtre=image,description
 *     ?lang=ar-SA
 *     ?tri=note:desc&puis=popularite:desc
 *     ?id=1399&lang=ar-SA&filtre=description
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

/** Les noms des tris dans l'URL, et leur clé côté API. Même parti pris que les
 *  filtres : `?tri=note:desc` se lit, `?sort=rating&order=desc` se décode. */
const TRIS = {
  date: 'air_date',
  annee: 'air_year',
  titre: 'name',
  note: 'rating',
  popularite: 'popularity',
  collecte: 'fetched',
} as const

type NomDeTri = keyof typeof TRIS

const CLE_VERS_NOM = Object.fromEntries(
  Object.entries(TRIS).map(([nom, cle]) => [cle, nom]),
) as Record<string, NomDeTri>

/** La valeur qui dit « pas de second critère ».
 *
 *  Elle doit exister : le défaut de l'application *a* un second critère (la
 *  popularité). Sans mot pour dire son absence, l'avoir retiré ne survivrait
 *  pas au partage de l'URL — le destinataire retomberait sur le défaut. */
const AUCUN = 'aucun'

export interface Tri {
  /** La clé d'API (`air_year`, `rating`…), ou `''` pour « aucun ». */
  cle: string
  sens: 'asc' | 'desc'
}

/** `note:desc` → `{ cle: 'rating', sens: 'desc' }`. Un nom inconnu rend null :
 *  `?tri=nimportequoi` laisse le défaut plutôt que d'envoyer l'API en 422. */
function lireTri(valeur: string | null, aucunPermis = false): Tri | null {
  if (valeur === null) return null
  const [nom, sens] = valeur.split(':')
  if (aucunPermis && nom === AUCUN) return { cle: '', sens: 'desc' }
  if (!(nom in TRIS)) return null
  return {
    cle: TRIS[nom as NomDeTri],
    // Le sens est facultatif : `?tri=note` se tape plus vite que
    // `?tri=note:desc`, et « les mieux notées » est ce qu'on veut neuf fois
    // sur dix. Seul `asc` renverse.
    sens: sens === 'asc' ? 'asc' : 'desc',
  }
}

function ecrireTri(tri: Tri): string {
  if (!tri.cle) return AUCUN
  return `${CLE_VERS_NOM[tri.cle] ?? tri.cle}:${tri.sens}`
}

/** Les onglets de la fiche, tels qu'ils s'écrivent dans l'URL. `presentation`
 *  est le défaut et ne s'écrit pas : `?id=1399` ouvre la fiche, et seul
 *  `?id=1399&onglet=training1` a quelque chose à préciser. */
const ONGLETS = ['presentation', 'training1', 'training2'] as const
type Onglet = (typeof ONGLETS)[number]

export interface UrlState {
  /** La fiche à ouvrir, ou null. */
  id: number | null
  /** L'onglet de la fiche — n'a de sens qu'avec `id`. */
  onglet: Onglet
  /** La langue choisie, ou null pour garder celle par défaut. */
  lang: string | null
  /** Le tri principal, ou null pour garder celui par défaut. */
  tri: Tri | null
  /** Le départage — `cle: ''` veut dire « aucun », explicitement. */
  puis: Tri | null
  withPoster: boolean
  withOverview: boolean
}

// Un code BCP-47 avec sa région : `fr-FR`, `ar-SA`. La forme est vérifiée ici,
// l'appartenance à la liste des langues connues ne peut l'être qu'une fois
// `meta` chargée — d'où le repli côté application plutôt qu'ici.
const CODE_LANGUE = /^[a-z]{2}-[A-Z]{2}$/

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

  const lang = params.get('lang')

  // Un onglet inconnu retombe sur la présentation, comme un tri inconnu garde
  // le défaut : une URL abîmée ouvre quelque chose plutôt que rien.
  const onglet = params.get('onglet')

  return {
    id: Number.isInteger(id) && id > 0 ? id : null,
    onglet: ONGLETS.includes(onglet as Onglet) ? (onglet as Onglet) : 'presentation',
    lang: lang !== null && CODE_LANGUE.test(lang) ? lang : null,
    tri: lireTri(params.get('tri')),
    puis: lireTri(params.get('puis'), true),
    withPoster: actifs.includes('image'),
    withOverview: actifs.includes('description'),
  }
}

export function writeUrl(state: UrlState, replace = true): void {
  // On repart des paramètres existants : ceux qu'on ne connaît pas — un
  // `?utm_source`, un futur `?vue` — n'ont pas à disparaître parce qu'on a
  // coché une case.
  const params = new URLSearchParams(window.location.search)

  if (state.id !== null) params.set('id', String(state.id))
  else params.delete('id')

  // L'onglet n'existe qu'attaché à une fiche, et la présentation est le
  // défaut : dans les deux cas, rien à écrire.
  if (state.id !== null && state.onglet !== 'presentation') params.set('onglet', state.onglet)
  else params.delete('onglet')

  // La langue est toujours écrite, même quand c'est celle par défaut : une URL
  // partagée doit ouvrir la même vue chez l'autre, y compris si son défaut
  // venait à changer.
  if (state.lang !== null) params.set('lang', state.lang)
  else params.delete('lang')

  // Les deux tris sont toujours écrits, comme la langue et pour la même
  // raison : une URL partagée doit ouvrir la même vue chez l'autre, y compris
  // le jour où le défaut de l'application changera.
  if (state.tri !== null) params.set('tri', ecrireTri(state.tri))
  else params.delete('tri')

  if (state.puis !== null) params.set('puis', ecrireTri(state.puis))
  else params.delete('puis')

  const filtres = (Object.keys(FILTRES) as (keyof typeof FILTRES)[]).filter(
    (nom) => state[FILTRES[nom]],
  )
  if (filtres.length > 0) params.set('filtre', filtres.join(','))
  else params.delete('filtre')

  // `URLSearchParams` encode la virgule en `%2C` et le deux-points en `%3A`.
  // Les deux sont pourtant légaux tels quels dans une chaîne de requête
  // (RFC 3986, sous-délimiteurs), et `?filtre=image,description&tri=note:desc`
  // se lit et se retape, contrairement à sa version encodée. On les remet en
  // clair : c'est la même URL pour le serveur, une URL utilisable pour un
  // humain.
  const query = params.toString().replace(/%2C/g, ',').replace(/%3A/g, ':')
  const url = query ? `${window.location.pathname}?${query}` : window.location.pathname

  // Rien à faire si l'URL ne change pas : `replaceState` à chaque rendu
  // encombrerait les outils de développement sans aucun effet visible.
  if (url === window.location.pathname + window.location.search) return
  if (replace) window.history.replaceState(null, '', url)
  else window.history.pushState(null, '', url)
}
