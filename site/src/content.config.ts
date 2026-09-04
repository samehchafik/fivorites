// Les collections de contenu — le « CMS » du site.
//
// Une page SEO est un fichier Markdown de `src/content/pages/`, versionné
// avec le code : produit à la main ou assisté par IA, relu en diff comme tout
// le reste. Le schéma ci-dessous est le contrat — un fichier qui ne le
// respecte pas casse le build, pas la production.
import { defineCollection, z } from 'astro:content'
import { glob } from 'astro/loaders'

const pages = defineCollection({
  loader: glob({ base: './src/content/pages', pattern: '**/*.md' }),
  schema: z.object({
    // Le <title> et le H1 de la page.
    titre: z.string(),
    // La meta description — ce que les moteurs affichent sous le lien.
    description: z.string().max(180),
    // La ligne rouge en capitales au-dessus du héros — « LE **TOP** DE LA
    // CULTURE **POP**, SUR MESURE ! ». Les ** marquent les graisses.
    surTitre: z.string().optional(),
    // L'accroche serif du héros (« Plus rien à regarder ? Écouter ? Lire ? »).
    accroche: z.string().optional(),
    // Les phrases du héros, sous l'accroche — le texte de conversion.
    phrases: z.array(z.string()).optional(),
    // L'univers que le composant de suggestion doit présélectionner sur
    // cette page. Absent = la home, qui laisse le choix.
    univers: z.enum(['series', 'films', 'livres']).optional(),
    // --- Les sections de la home, d'après la maquette du designer ---------
    // « Comment ça marche ? » : le titre et les étapes numérotées.
    commentTitre: z.string().optional(),
    etapes: z.array(z.string()).optional(),
    // « L'empreinte culturelle » : titre + paragraphes, illustrés par le
    // slider des mosaïques d'affiches.
    empreinteTitre: z.string().optional(),
    empreinte: z.array(z.string()).optional(),
    // Le teaser des salons de discussion (la fonctionnalité arrive).
    salonsTitre: z.string().optional(),
    salonsTexte: z.string().optional(),
  }),
})

export const collections = { pages }
