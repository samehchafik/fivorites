// La langue de l'îlot — et pourquoi c'est l'URL qui la décide.
//
// Il y a eu trois candidats : ce que le navigateur préfère, ce que le
// visiteur avait choisi la dernière fois (localStorage), et la page où il se
// trouve. Les deux premiers produisaient la même faute, vue à l'écran :
// arriver sur `/ar/series` donnait une coque arabe, de droite à gauche, avec
// un composant en français au milieu. Et cliquer « AR » dans l'en-tête ne
// changeait rien au composant, puisqu'un ancien choix « fr » traînait dans le
// navigateur.
//
// Donc : **l'URL décide, seule.** Une page, une langue, entière. Le sélecteur
// du composant ne modifie plus un état local — il NAVIGUE vers la même page
// dans l'autre langue, ce qui fait suivre la coque, le contenu Markdown, les
// balises `hreflang` et l'îlot d'un seul mouvement.

import {
  LANGUES,
  LANGUE_DEFAUT,
  LANGUE_NOMS,
  chemin_localise,
  chemin_sans_langue,
  type Langue,
} from '../../i18n/langues'

export { LANGUES, LANGUE_DEFAUT, LANGUE_NOMS as LANGUE_LABELS }
export type { Langue }

/** L'adresse de la page courante dans une autre langue. */
export function adresse_dans(langue: Langue): string {
  const chemin = typeof location === 'undefined' ? '/' : location.pathname
  return chemin_localise(chemin_sans_langue(chemin), langue)
}
