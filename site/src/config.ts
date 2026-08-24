// Le réglage d'ouverture du site — UN drapeau, trois effets.
//
// Tant que `AVANT_PREMIERE` est vrai :
//   * chaque page porte <meta name="robots" content="noindex, nofollow"> ;
//   * /robots.txt interdit tout (src/pages/robots.txt.ts lit ce drapeau) ;
//   * une modale d'entrée couvre la page — OK la révèle, et le choix est
//     retenu dans le navigateur (localStorage).
//
// L'ouverture au public, le jour venu : passer à `false`, `make -C site
// build`, committer www-site/ — et rien d'autre : les meta, le robots.txt et
// la modale suivent tous ce drapeau, il n'y a pas de deuxième endroit à
// penser.
export const AVANT_PREMIERE = true
