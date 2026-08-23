// La configuration Astro du site public.
//
// Pourquoi Astro : les pages sortent en HTML PUR — zéro JavaScript par défaut,
// ce qui est exactement le contrat SEO — et les composants React s'y montent
// en îlots (`client:load`) là où il faut de l'interactivité : le composant
// « FIVO, suggère-moi… » et rien d'autre. Le contenu des pages vit en
// Markdown versionné (`src/content/`), produit et retouché à la main ou par
// IA : le CMS, c'est le dépôt.
import react from '@astrojs/react'
import { defineConfig } from 'astro/config'

export default defineConfig({
  integrations: [react()],

  // Le build versionné, servi par le service webapp — même convention que
  // `www/` pour l'admin : sur le serveur il arrive par `git pull`, pas de
  // Node là-bas.
  outDir: '../www-site',

  vite: {
    server: {
      // En dev, Astro sert le site sur 4321 et relaie l'API vers le service
      // webapp sur 8183 : le front parle toujours à la même origine, en dev
      // comme en production — pas de CORS à raisonner côté navigateur.
      proxy: {
        '/api': 'http://127.0.0.1:8183',
      },
    },
  },
})
