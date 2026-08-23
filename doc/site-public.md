# Le site public — la première brique du front V2

*Écrit le 23 août 2026, à la naissance des modules `webapp/`, `site/` et
`www-site/`. Ce document dit ce qui a été décidé et pourquoi ; le comment vit
dans les en-têtes de modules.*

## Ce qu'on construit

Le site public de Fivorites, dans le design de la V1, réduit pour commencer à
trois univers — séries, films, livres — et à un parcours : la home porte le
composant **« FIVO, suggère-moi… »**, où un visiteur cherche des œuvres en
temps réel, les classe (*j'ai vu et aimé*, *je n'aime pas*, *je veux voir*),
et reçoit des suggestions expliquées. Pas de compte : une session anonyme,
posée au premier geste.

Trois décisions structurantes, prises ensemble au démarrage :

## 1. Astro comme fabrique de pages, le dépôt comme CMS

Le besoin SEO était : des pages en HTML pur, produites par un outil robuste
et assisté par IA. Les candidats regardés : Next.js (SSR complet, mais Node
en production — contraire à la convention « le serveur fait `git pull`, pas
de build là-bas »), un CMS headless (une interface d'édition, mais un service
de plus à héberger et à sauvegarder), et **Astro** — retenu.

Ce qu'Astro donne exactement :

* les pages sortent en **HTML statique sans JavaScript** ; le JS n'entre que
  par les îlots React déclarés un à un (`client:load`) — ici un seul, le
  composant de suggestion. Le contrat SEO est structurel, pas discipliné ;
* le contenu vit en **Markdown versionné** (`site/src/content/pages/`),
  validé par un schéma zod (`content.config.ts`) : une page assistée par IA
  est un fichier qu'on relit en diff, et un fichier hors contrat casse le
  build — jamais la production. Le CMS, c'est le dépôt ;
* le build (`make -C site build`) sort dans **`www-site/`, versionné** —
  la convention de `www/` pour l'admin, à l'identique.

## 2. Un second service FastAPI, pas une extension de l'admin

`webapp/` (port 8183) est un service séparé de `admin/` (8182). La frontière
n'est pas cosmétique : l'admin est verrouillée derrière un login et sert un
front `noindex` ; le site public est fait pour être indexé et servi à tout le
monde. Les mélanger reviendrait à surveiller en permanence que le catch-all
statique de l'un ne recouvre pas les routes de l'autre, et que rien de public
ne s'ouvre par accident sur `/api/*` privé.

Le service **lit** ce que l'admin entretient — les projections
`admin.*_card`, les index Elasticsearch, le graphe Neo4j — et n'écrit que
dans son schéma à lui, **`visiteur`** : la session anonyme
(`visiteur.session`) et ses signaux (`visiteur.signal`, un par couple
session × œuvre, trois statuts exclusifs). L'identité manipulée est toujours
le pivot `sourcing.oeuvre.id` — la seule clé commune aux trois univers, et
celle que le graphe porte.

La session anonyme est le choix de démarrage assumé : l'outil marche sans
inscription, un cookie signé (HMAC, 180 jours) porte l'identifiant, et le
jour des vrais comptes une colonne `membre_id` nullable rattachera les
sessions aux membres sans rien perdre.

## 3. Les suggestions : les voisins d'abord, la distance pour compléter

Le moteur (`webapp/src/fiv_webapp/suggestions.py`) a deux étages, parce que
le graphe a deux savoirs :

1. **La communauté.** Les voisins — les membres V1 qui ont cité les mêmes
   œuvres que celles que le visiteur a aimées, plafonnés à 50, les plus
   proches d'abord — et ce qu'ils citent que le visiteur n'a pas classé.
   Classement : nombre de voisins qui portent l'œuvre, puis rang moyen dans
   leurs tops (la première place pèse plus que la cinquième) — la formule du
   graphe d'admin (`routes/membres.py`).
2. **L'empreinte.** Quand la communauté ne remplit pas la liste, l'index
   vectoriel euclidien `fivEmpreinteVoisins` complète par distance
   croissante. La distance se lit en points de note et elle est **plafonnée à
   2,0** (~2,4 × le MAE de 0,84) : au-delà, ce n'est plus « ce que vous
   cherchez », et la liste préfère rester courte que mentir.

Tout ce qui a été classé est exclu, quel que soit le statut, et chaque
suggestion porte sa raison (`voisins` + force, ou `distance`) — le composant
l'affiche : une suggestion inexpliquée ressemble à de la publicité.

## Le front : Mantine habillé de la charte V1

Le composant React est construit sur **Mantine** (le framework du front
d'admin — mêmes composants, mêmes habitudes, comportements et accessibilité
éprouvés au lieu d'inventions maison), et habillé de la **charte V1**
extraite du dépôt `fivorites` : le carmin `#FA0036 → #700031` (le couple
`--fivorites1/2` de tous les dégradés), Fira Sans et Libre Baskerville
auto-hébergées, le SVG de l'étoile (logo, filigrane du panneau, fond des
affiches manquantes), le fond étoilé `homeback.png`, les puces `▶︎` de la
navigation, et les couleurs des trois gestes (`--pink` pour aimé, `--no`,
`--yes`). Les assets sont copiés dans `site/public/` ; les valeurs vivent
dans `site/src/styles/global.css` et `site/src/components/fivo/fivo.css`.

## La recherche du composant

Le chemin critique — une requête par frappe débouncée — réutilise les index
de l'admin tels quels : `match` sur les préfixes `edge_ngram` posés à
l'indexation, phrase exacte boostée, classement multiplié par la note
bayésienne (jamais `popularity`, biais occidental documenté), `fiche: true`
toujours (on ne classe que ce qu'on peut montrer). Pas de pagination : une
frappe rend une page courte, sinon on précise la requête. ES absent ou en
panne → disjoncteur 30 s et repli ILIKE sur la projection ; la réponse dit
quel moteur a servi.

## Ce qui reste devant

* **Neo4j en local** : le poste n'a pas encore de Neo4j vendorisé dans ce
  module — les suggestions se testent contre le serveur ou après `make -C
  admin bootstrap-neo4j` ; le moteur, lui, est couvert par des tests
  unitaires sur faux graphe.
* **Les comptes membres** : rattacher les sessions anonymes à `membre.*`
  (import V1), et l'app React « connectée » complète.
* **BD et musiques** : entreront par `webapp/src/fiv_webapp/univers.py` et
  une entrée de contenu — nulle part ailleurs.
* **Le sitemap et les pages de taxonomie SEO** (par origine notamment — voir
  `doc/etude-couverture-marche-arabe.md` §4) : la structure Astro les attend.
