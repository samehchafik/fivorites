// Le bus du compte : deux îlots React vivent sur la page — le module de
// suggestion et le menu de l'en-tête — et chacun a son propre arbre. Un
// CustomEvent sur `window` les tient d'accord : qui change le compte
// l'annonce, l'autre l'apprend. Pas de store partagé, pas de contexte
// commun — deux événements nommés, et c'est tout.

import type { Compte } from './types'

const COMPTE = 'fivo:compte'
const CONNEXION = 'fivo:ouvrir-connexion'

/** Annonce le compte (ou sa disparition) à tous les îlots de la page. */
export function annoncerCompte(compte: Compte | null): void {
  window.dispatchEvent(new CustomEvent(COMPTE, { detail: compte }))
}

/** Écoute les annonces — rend la fonction de désabonnement. */
export function surCompte(recoit: (compte: Compte | null) => void): () => void {
  const gestionnaire = (evenement: Event) =>
    recoit((evenement as CustomEvent<Compte | null>).detail ?? null)
  window.addEventListener(COMPTE, gestionnaire)
  return () => window.removeEventListener(COMPTE, gestionnaire)
}

/** Demande au module d'ouvrir sa modale de connexion (depuis l'en-tête). */
export function demanderConnexion(): void {
  window.dispatchEvent(new CustomEvent(CONNEXION))
}

export function surDemandeConnexion(recoit: () => void): () => void {
  window.addEventListener(CONNEXION, recoit)
  return () => window.removeEventListener(CONNEXION, recoit)
}
