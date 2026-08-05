import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const PACKAGE = fileURLToPath(new URL('./package.json', import.meta.url))

/**
 * Le numéro de version du front, incrémenté à chaque build.
 *
 * Il vit dans le `version` de `package.json` plutôt que dans un fichier à part :
 * c'est le champ que tout le monde regarde en premier, et un second compteur
 * ailleurs finirait par diverger de celui-là.
 *
 * Conséquence assumée : **un build modifie un fichier suivi par git.** C'est le
 * prix d'un compteur qui survit d'un build à l'autre — un numéro tiré de
 * l'horodatage ou du hachage n'aurait rien à incrémenter, et un numéro non
 * versionné repartirait de zéro à chaque clone.
 */
function bumpVersion(): string {
  const pkg = JSON.parse(readFileSync(PACKAGE, 'utf8')) as { version: string }
  const [major = 0, minor = 0, patch = 0] = pkg.version.split('.').map(Number)
  pkg.version = `${major}.${minor}.${patch + 1}`
  // `null, 2` et le saut de ligne final : le format qu'écrit npm. Sans ça,
  // chaque build produirait un diff sur tout le fichier.
  writeFileSync(PACKAGE, `${JSON.stringify(pkg, null, 2)}\n`)
  return pkg.version
}

function readVersion(): string {
  return (JSON.parse(readFileSync(PACKAGE, 'utf8')) as { version: string }).version
}

/**
 * Ajoute `?version=x.y.z` aux fichiers référencés par `index.html`.
 *
 * Les noms de fichiers sont fixes (`index.js`, `style.css`) : sans empreinte
 * dans le nom, un navigateur qui a l'ancien fichier en cache n'a aucune raison
 * de le redemander. C'est la requête qui porte la version, et une requête
 * différente est une entrée de cache différente — pour le navigateur comme pour
 * les intermédiaires.
 *
 * `enforce: 'post'` : on réécrit les balises que Vite vient d'injecter, donc
 * après lui.
 */
function versionQuery(version: string): Plugin {
  return {
    name: 'fivorites-version-query',
    enforce: 'post',
    apply: 'build',
    transformIndexHtml(html) {
      return html.replace(/(src|href)="(\/assets\/[^"?]+)"/g, `$1="$2?version=${version}"`)
    },
  }
}

// Les sources vivent ici, le build sort dans `../www`.
//
// Cette séparation est le contrat avec l'API : `www/` est le **répertoire
// statique**, et rien d'autre — un `index.html`, ses fichiers, et c'est tout.
// FastAPI le sert tel quel pour toute requête qui n'est pas `/api/*`. Y laisser
// `package.json`, `src/` ou `node_modules` reviendrait à publier le code du
// front et des dizaines de milliers de fichiers de dépendances.
//
// `emptyOutDir` est explicite parce que la cible est hors du répertoire racine
// de Vite : sans lui, Vite refuse de nettoyer `../www`, et les fichiers d'un
// build précédent s'accumuleraient à côté des nouveaux.
export default defineConfig(({ command }) => {
  // Un serveur de développement n'est pas un build : il ne fait pas avancer le
  // compteur. Sinon un `make dev` laissé ouvert une journée le ferait grimper
  // sans que rien n'ait été livré.
  const version = command === 'build' ? bumpVersion() : readVersion()

  return {
    plugins: [react(), versionQuery(version)],

    // Le numéro est aussi remis à l'application, qui l'affiche : savoir quelle
    // version est réellement servie évite le doute permanent du « est-ce que
    // mon changement est en ligne ? ».
    define: { __APP_VERSION__: JSON.stringify(version) },

    server: {
      port: 5173,
      // En développement, Vite relaie `/api` vers l'API Python. Le front et
      // l'API sont donc **une seule origine** vue du navigateur : le cookie de
      // session reste un cookie propriétaire, `SameSite=strict` fonctionne, et
      // il n'y a rien à configurer en CORS. En production la question ne se
      // pose pas — c'est l'API qui sert `www/`.
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8182',
          changeOrigin: false,
        },
      },
    },

    build: {
      outDir: '../www',
      emptyOutDir: true,
      // Pas de sourcemap dans le répertoire servi : une sourcemap, c'est le
      // code source complet et lisible, publié à côté du bundle. Ce serait
      // remettre dans `www/` exactement ce qu'on a pris soin de garder dans
      // `front/`. Le développement, lui, en a une : Vite en produit une à la
      // volée pour `make dev`.
      sourcemap: false,

      // Noms fixes plutôt que l'empreinte du contenu (`index-Cij1LZw0.js`).
      // Par défaut, chaque build produit des noms neufs : les anciens
      // s'accumulent partout où le répertoire est suivi ou synchronisé, et le
      // diff d'un déploiement est illisible. Ici trois fichiers, toujours les
      // mêmes — la fraîcheur est portée par `?version=`, pas par le nom.
      rollupOptions: {
        output: {
          entryFileNames: 'assets/index.js',
          chunkFileNames: 'assets/[name].js',
          assetFileNames: (asset) => {
            const name = asset.names?.[0] ?? ''
            return name.endsWith('.css') ? 'assets/style.css' : 'assets/[name][extname]'
          },
        },
      },
    },
  }
})
