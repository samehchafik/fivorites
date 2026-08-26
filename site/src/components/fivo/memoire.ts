// Le petit coin de mémoire du navigateur, pour les préférences d'affichage.
//
// Il existe parce que deux préférences s'y rangent déjà — la langue de
// recherche et la vue des suggestions — et qu'elles partageaient le même
// `try/catch` recopié. Le `try` n'est pas du zèle : en navigation privée, ou
// avec les données de site bloquées, le simple accès à `localStorage` LÈVE.
// Une préférence perdue n'est rien ; une page blanche à cause d'elle serait
// une faute.

/** La valeur retenue, ou `null` — jamais une exception. */
export function retenu(cle: string): string | null {
  try {
    return localStorage.getItem(cle)
  } catch {
    return null
  }
}

/** Retient une valeur. Silencieux en cas de refus : le choix vaut alors pour
 *  la session, ce qui est déjà l'essentiel. */
export function retenir(cle: string, valeur: string): void {
  try {
    localStorage.setItem(cle, valeur)
  } catch {
    // Sans mémoire, on continue : ce n'est pas une erreur de l'utilisateur.
  }
}
