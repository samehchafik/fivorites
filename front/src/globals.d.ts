/**
 * Le numéro de version du build, injecté par Vite (`define`, dans
 * `vite.config.ts`). Il vaut le `version` de `package.json`, incrémenté à
 * chaque build.
 *
 * Une constante remplacée à la compilation plutôt qu'un appel réseau : la
 * version affichée est celle du bundle qu'on est en train d'exécuter, pas celle
 * que le serveur croit avoir déployé. Quand les deux diffèrent, c'est
 * précisément ce qu'on cherche à savoir.
 */
declare const __APP_VERSION__: string
