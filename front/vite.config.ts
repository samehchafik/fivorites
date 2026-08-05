import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

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
// build précédent s'accumuleraient à côté des nouveaux — un `index.html` neuf
// servi à côté des empreintes périmées de l'ancien.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // En développement, Vite relaie `/api` vers l'API Python. Le front et l'API
    // sont donc **une seule origine** vue du navigateur : le cookie de session
    // reste un cookie propriétaire, `SameSite=strict` fonctionne, et il n'y a
    // rien à configurer en CORS. En production la question ne se pose pas —
    // c'est l'API qui sert `www/`.
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
    // Pas de sourcemap dans le répertoire servi : une sourcemap, c'est le code
    // source complet et lisible, publié à côté du bundle. Ce serait remettre
    // dans `www/` exactement ce qu'on a pris soin de garder dans `front/` — et
    // 2,7 Mo par-dessus le marché. Le développement, lui, en a une : Vite en
    // produit une à la volée pour `make dev`.
    sourcemap: false,
  },
})
