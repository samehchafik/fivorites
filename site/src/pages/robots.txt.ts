// /robots.txt, généré au build depuis le drapeau d'ouverture : un fichier
// statique dans public/ serait un deuxième endroit à penser le jour du
// lancement — et celui qu'on oublie.
import type { APIRoute } from 'astro'

import { AVANT_PREMIERE } from '../config'

const FERME = `# five.ifrit.fr — avant-première : rien à indexer pour l'instant.
User-agent: *
Disallow: /
`

const OUVERT = `# five.ifrit.fr — tout est indexable, et le sitemap dit quoi.
User-agent: *
Allow: /

Sitemap: https://five.ifrit.fr/sitemap-index.xml
`

export const GET: APIRoute = () =>
  new Response(AVANT_PREMIERE ? FERME : OUVERT, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  })
