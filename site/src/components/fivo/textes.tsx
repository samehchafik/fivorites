// Les textes de l'îlot, portés par un contexte plutôt que par des props.
//
// Pourquoi un contexte : la langue traverse TOUT le composant — le bandeau,
// les cartes, la pile, les trois modales, jusqu'au bouton « Passer ». La
// faire descendre en prop ajouterait un paramètre à quinze signatures et un
// oubli quelque part rendrait une phrase française au milieu de l'arabe.

import { createContext, useContext } from 'react'

import { LANGUE_DEFAUT } from '../../i18n/langues'
import { textes, type Textes } from '../../i18n/textes'

const Contexte = createContext<Textes>(textes(LANGUE_DEFAUT))

export const FournisseurTextes = Contexte.Provider

/** Les textes de la langue courante. */
export function useTextes(): Textes {
  return useContext(Contexte)
}
