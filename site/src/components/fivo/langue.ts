// La langue de recherche : celle du navigateur, ou celle qu'on choisit.
//
// Pourquoi ça existe : l'index porte les titres de ~45 langues. Sans langue,
// un francophone tapant « com » recevait des feuilletons portugais — *com* y
// est une préposition — affichés avec leur titre français. La liste devenait
// incompréhensible, et conclure au bug était raisonnable. On cherche donc
// dans la langue de qui cherche, et on affiche les titres dans cette langue.

/** Les langues servies — les mêmes que celles indexées (`fiv_admin.search`). */
export const LANGUES = ['fr', 'en', 'es', 'ar'] as const

export type Langue = (typeof LANGUES)[number]

export const LANGUE_DEFAUT: Langue = 'fr'

export const LANGUE_LABELS: Record<Langue, string> = {
  fr: 'Français',
  en: 'English',
  es: 'Español',
  ar: 'العربية',
}

import { retenir, retenu } from './memoire'

const CLE = 'fivo-langue'

function servie(brut: string | null | undefined): Langue | null {
  const racine = (brut ?? '').split('-')[0]?.toLowerCase()
  return (LANGUES as readonly string[]).includes(racine) ? (racine as Langue) : null
}

/** La langue de départ : le choix retenu s'il y en a un, sinon celle du
 *  navigateur, sinon le français.
 *
 *  `navigator.languages` est parcouru dans l'ordre des préférences : un
 *  navigateur réglé sur « pt-BR, fr » n'a pas de portugais servi, mais son
 *  second choix, oui — le prendre vaut mieux que retomber sur le défaut. */
export function langueInitiale(): Langue {
  const choisie = servie(retenu(CLE))
  if (choisie) return choisie
  if (typeof navigator !== 'undefined') {
    for (const candidate of navigator.languages ?? [navigator.language]) {
      const trouvee = servie(candidate)
      if (trouvee) return trouvee
    }
  }
  return LANGUE_DEFAUT
}

/** Retient le choix pour les visites suivantes. */
export function retenirLangue(langue: Langue): void {
  retenir(CLE, langue)
}
