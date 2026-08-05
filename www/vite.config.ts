import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En développement, Vite relaie `/api` vers l'API Python. Le front et l'API
// sont donc **une seule origine** vue du navigateur : le cookie de session
// reste un cookie propriétaire, `SameSite=strict` fonctionne, et il n'y a rien
// à configurer en CORS. En production la question ne se pose pas — l'API sert
// elle-même le contenu de `dist/`.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8182',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
