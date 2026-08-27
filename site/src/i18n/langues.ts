// Les quatre langues du site — la liste de référence, côté pages comme côté
// îlot React.
//
// Elle existe en un seul endroit pour une raison mesurée : l'index porte les
// titres de ~45 langues, et un francophone tapant « com » recevait des
// feuilletons portugais (*com* y est une préposition) affichés avec leur
// titre français. La langue n'est donc pas un détail d'affichage : elle
// décide de ce qu'on cherche, de ce qu'on lit, et du sens de la page.

export const LANGUES = ['fr', 'en', 'es', 'ar'] as const

export type Langue = (typeof LANGUES)[number]

/** Le français : la langue de la collecte, et celle des routes sans préfixe. */
export const LANGUE_DEFAUT: Langue = 'fr'

/** Chaque langue nommée DANS sa langue : c'est la seule façon qu'un
 *  arabophone reconnaisse la sienne dans une liste qu'il ne lit pas encore. */
export const LANGUE_NOMS: Record<Langue, string> = {
  fr: 'Français',
  en: 'English',
  es: 'Español',
  ar: 'العربية',
}

/** Le drapeau de chaque langue.
 *
 *  Un drapeau désigne un PAYS, pas une langue : l'arabe ne se parle pas qu'en
 *  Arabie saoudite ni l'anglais qu'au Royaume-Uni. C'est un raccourci assumé,
 *  pour la place qu'il fait gagner sur un téléphone — et il n'est jamais
 *  seul : le nom de la langue l'accompagne, en texte lisible ou en étiquette
 *  accessible. Le pays retenu est celui que le serveur utilise déjà pour lire
 *  la disponibilité des plateformes (`fiv_webapp.fiche.PAYS_DE_LANGUE`), pour
 *  ne pas avoir deux réponses à la même question.
 *
 *  Ces caractères sont des paires d'indicateurs régionaux : sans police
 *  d'emoji drapeaux — Windows n'en a pas — ils s'affichent « FR », « GB »,
 *  c'est-à-dire exactement le code qu'on montrait avant. La dégradation est
 *  lisible, et c'est pour ça qu'on peut s'en servir. */
export const LANGUE_DRAPEAUX: Record<Langue, string> = {
  fr: '🇫🇷',
  en: '🇬🇧',
  es: '🇪🇸',
  ar: '🇸🇦',
}

/** Le sens d'écriture. L'arabe se lit de droite à gauche : `dir` sur la
 *  racine retourne la mise en page entière, y compris les marges logiques. */
export const LANGUE_SENS: Record<Langue, 'ltr' | 'rtl'> = {
  fr: 'ltr',
  en: 'ltr',
  es: 'ltr',
  ar: 'rtl',
}

/** L'étiquette de langue pour `Intl` — le formatage des nombres en dépend
 *  (séparateurs, chiffres arabes-indiens). */
export const LANGUE_LOCALES: Record<Langue, string> = {
  fr: 'fr-FR',
  en: 'en-US',
  es: 'es-ES',
  ar: 'ar',
}

/** La langue d'un code quelconque (« fr-CA », « AR », null…), ou `null`.
 *  Sert autant à lire `navigator.languages` qu'un segment d'URL. */
export function langue_servie(brut: string | null | undefined): Langue | null {
  const racine = (brut ?? '').split('-')[0]?.toLowerCase()
  return (LANGUES as readonly string[]).includes(racine) ? (racine as Langue) : null
}

/** Le préfixe d'URL d'une langue : rien pour le français, `/en` ailleurs.
 *
 *  Le français reste à la racine parce que le site y était déjà indexé :
 *  déplacer `/series` vers `/fr/series` casserait les liens existants pour
 *  ne gagner qu'une symétrie. */
export function prefixe_langue(langue: Langue): string {
  return langue === LANGUE_DEFAUT ? '' : `/${langue}`
}

/** Le chemin d'une page dans une langue : `chemin_localise('/series', 'ar')`
 *  → `/ar/series`. */
export function chemin_localise(chemin: string, langue: Langue): string {
  const propre = chemin === '/' ? '' : chemin.replace(/\/$/, '')
  return `${prefixe_langue(langue)}${propre}` || '/'
}

/** La langue portée par un chemin d'URL, ou le français. */
export function langue_du_chemin(chemin: string): Langue {
  return langue_servie(chemin.split('/').filter(Boolean)[0]) ?? LANGUE_DEFAUT
}

/** Le chemin débarrassé de son préfixe de langue : `/ar/series` → `/series`.
 *
 *  C'est l'opération inverse de `chemin_localise`, et les deux ensemble
 *  permettent de passer d'une langue à l'autre SANS quitter la page qu'on
 *  regarde — changer de langue depuis les films doit mener aux films. */
export function chemin_sans_langue(chemin: string): string {
  const morceaux = chemin.split('/').filter(Boolean)
  if (morceaux.length > 0 && langue_servie(morceaux[0])) morceaux.shift()
  return `/${morceaux.join('/')}`.replace(/\/$/, '') || '/'
}
