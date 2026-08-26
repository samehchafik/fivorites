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

## 3. Les suggestions : une fusion pondérée, pas une cascade

*Réécrit le 26 août 2026. La première version était une cascade — les tops
des voisins, puis l'empreinte, puis les affinités — et c'était une erreur de
conception : **le savoir communautaire vient de la V1, arrêté en 2019.** Il
remplissait les vingt-quatre places, si bien que qui aime une œuvre récente
n'était servi que par des tops qui ne la connaissent pas, et que les sources
capables de le servir ne s'exécutaient jamais. Une cascade fait de son
premier étage un plafond.*

Le moteur (`webapp/src/fiv_webapp/suggestions.py`) part des **listes du
visiteur**, pondérées par ce qu'elles disent :

| Liste | Poids | Pourquoi |
|---|---|---|
| `aime` — vu et aimé | 1,0 | un verdict |
| `a_voir` — je veux voir | 0,4 | une intention : elle dit le goût sans le prouver |
| `aime_pas` | — | exclue des graines et des résultats |

Trois sources versent ensuite un **apport chiffré** sur chaque candidat, et le
classement se fait sur le total — aucune ne peut donc occuper la liste seule :

1. **Les voisins d'œuvre par empreinte** (Neo4j, index vectoriel euclidien
   `fivEmpreinteVoisins`). L'apport décroît linéairement avec la distance et
   s'annule à 2,0 points de note (~2,4 × le MAE de 0,84), et il est **pondéré
   par la graine** : être à 0,3 point d'une œuvre vue et aimée vaut plus
   qu'être à 0,3 point d'une œuvre qu'on veut voir. Cette source ne périme
   pas — une œuvre notée hier est aussi proche qu'une œuvre de 2019.
2. **La communauté** (Neo4j : les membres qui citent les graines, puis ce
   qu'ils citent d'autre). Apport relatif au plus cité de la fournée, modulé
   par le rang moyen dans les tops. C'est le savoir de 2019, et il a
   désormais le poids d'une source parmi trois.
3. **Les affinités** (Elasticsearch : genres et gens des graines). Le signal
   le plus faible, le seul qui ait toujours de la matière, et le seul qui ne
   demande pas Neo4j — c'est lui qui garantit une réponse.

Et le geste qui fait la qualité : **la corroboration**. Quand une œuvre est à
la fois proche par le contenu (empreinte ou affinités) ET portée par la
communauté, son total est multiplié par 1,8. Deux savoirs indépendants qui
désignent la même œuvre valent mieux que deux fois le même — c'est ce qui
laisse la communauté peser fort là où elle a raison, sans lui laisser tenir la
liste là où elle est muette. L'explication affichée le dit : « Proche de vos
coups de cœur ET dans le top de 4 membres qui partagent vos goûts ».

Un choix à connaître : quand plusieurs graines désignent le même candidat,
c'est le **meilleur** apport qui compte, pas leur somme — sinon un profil
large écraserait un profil précis. Si les listes rendues paraissent trop
étroites, c'est le premier réglage à revoir (`Candidat.verser`).

Tout ce qui a été classé est exclu, quel que soit le statut.

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

*Complété le 26 août 2026 : ce qui suit a été ajouté après des essais à
l'écran, chaque point corrigeant un défaut constaté.*

Le chemin critique — une requête par frappe débouncée — réutilise les index
de l'admin. Ce qui a changé depuis la première version :

* **Le titre principal domine le classement.** `titres` aplatit ~45 langues
  dans un champ unique, si bien qu'une frappe courte tombait sur un mot
  courant d'une autre langue : « com » rendait *Morangos com Açúcar* et le
  titre portugais du *Fils de Sam*, *com* y étant une préposition. Un champ
  `titre_principal` (nom courant et titre original, sans les traductions)
  passe devant, d'un facteur 4 — pas d'un cheveu : la note bayésienne
  multiplie le score et renversait un écart plus mince (mesuré à 29,1 contre
  28,8 avant, 81,7 contre 35,0 après).
* **Les titres sont indexés par langue** (fr, en, es, ar) et la requête
  cherche dans la langue de qui cherche, qui vient du navigateur et se change
  par un sélecteur. Le champ fourre-tout reste, en dernier rang, pour
  retrouver une œuvre dont on ne connaît que le titre en turc. L'arabe a sa
  propre chaîne d'analyse : l'article défini se colle au mot, si bien que
  « سيد الخواتم » s'indexait en `الخواتم` et que taper `خواتم` ne trouvait
  rien.
* **Le titre affiché suit la langue demandée**, et il vient de l'index : la
  projection n'en porte qu'un, celui de la collecte. Le synopsis, lui, reste
  français — limite connue.
* **Les filtres** sont peuplés par une agrégation sur l'index, donc par ce que
  le catalogue contient vraiment. La dimension s'adapte : genres pour les
  séries et les films, **langues** pour les livres, qui n'ont aucun genre en
  base (Wikidata ne rend qu'auteurs, langues, pays, année). Le jour où le
  crawler collectera P136, deux lignes de `univers.py` suffiront.
* **La liste se pagine** : total annoncé (compté jusqu'à 500, puis « plus
  de »), et un bouton qui ajoute à la suite. Le repli SQL pagine et filtre
  lui aussi.

ES absent ou en panne → disjoncteur 30 s et repli ILIKE sur la projection ; la
réponse dit quel moteur a servi.

⚠️ Chacun de ces lots a changé le **mapping** : `search reindex` est à
repasser par univers au déploiement. Et sur le poste, la commande ne
s'invoque que par le script console `fiv-admin` — `python -m fiv_admin.cli`
ne lance pas l'application Typer et sort silencieusement en 0, ce qui a fait
croire à deux réindexations réussies qui n'avaient rien fait.

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
