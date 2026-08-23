# site — le front public (Astro + React)

Les pages SEO du site public, en HTML pur, avec UN îlot React : le composant
« FIVO, suggère-moi… » (recherche instantanée + classement + suggestions),
construit sur **Mantine** et habillé de la **charte V1** — le carmin
`#FA0036 → #700031`, Fira Sans, Libre Baskerville, l'étoile et le fond étoilé
repris du dépôt V1.

Le « CMS », c'est le dépôt : chaque page est un Markdown de
`src/content/pages/` validé par le schéma de `src/content.config.ts` —
produit à la main ou assisté par IA, relu en diff, et un fichier hors contrat
casse le build, pas la production.

## Démarrer

```
make bootstrap   # Node vendorisé + dépendances
make dev         # Astro sur 4321, /api relayé vers l'API webapp (8183)
make build       # construit ../www-site — le build VERSIONNÉ que webapp sert
```

Même convention que `www/` pour l'admin : `www-site/` se commite avec le code
(`make build` avant de committer), et le déploiement est un `git pull` — pas
de Node sur le serveur.

Le raisonnement complet est dans [`doc/site-public.md`](../doc/site-public.md).
