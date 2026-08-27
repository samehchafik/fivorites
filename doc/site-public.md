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

## Le moteur, deuxième refonte : la base est figée, le moteur ne l'est plus

*Ajouté le 27 août 2026. La fusion pondérée restait trop portée par les
voisins des membres — or la base communautaire est figée : plus un membre
nouveau depuis des années, donc un savoir qui vieillit sans se corriger.*

Cinq gestes, chacun mesurable :

1. **Le profil du visiteur — ses axes.** Chaque œuvre notée porte une
   empreinte en six axes ; le visiteur en a une aussi désormais : le centre
   pondéré de ses « vus et aimés » et de ses envies, POUSSÉ à l'écart du
   centre de ses « j'aime pas ». C'est le seul endroit où le rejet travaille
   au lieu de seulement filtrer. Le repoussoir est calibré sur la production
   (×0,15) : à ×0,5, un profil « Lucifer + Shadowhunters, rejet Pokémon »
   était expulsé hors du nuage et retombait sur des dramas sans rapport ; à
   ×0,15 il garde ses voisins de goût (Sabrina, Ma sorcière bien-aimée) avec
   l'animation en retrait. Une seule requête vectorielle, source `profil`.
2. **La convergence.** Être le voisin de trois graines dit plus qu'être le
   voisin d'une seule : la meilleure contribution fait la base, chaque graine
   supplémentaire ajoute 35 % de la sienne, sous plafond. L'explication le
   dit : « Empreinte proche de N de vos œuvres ».
3. **La fraîcheur.** Le score final est multiplié par un facteur d'âge
   (plancher 0,55, constante 12 ans) : la liste se lit du plus récent au plus
   vieux sans devenir un tri aveugle — un chef-d'œuvre ancien très proche du
   profil bat encore une nouveauté qui ne l'est guère.
4. **La communauté rétrogradée** (apport 0,8 → 0,45) : elle corrobore et
   départage, elle ne conduit plus. Les envies gagnent du poids (0,4 → 0,6)
   et quatre places de graines leur sont réservées — un simple tri par poids
   les évinçait dès douze « aimés ».
5. **« Sur : » — le filtre de plateformes** (séries et films). Les
   suggestions arrivent avec leurs plateformes — lues du brut TMDB
   (`watch/providers`) dans le pays de la langue, offres regardables
   seulement (abonnement et gratuit, pas la location), variantes repliées sur
   l'enseigne (« Netflix Standard with Ads » est du Netflix). Des puces
   POSITIVES : cocher Netflix ne garde que ce qui s'y regarde
   (`?sur=Netflix`), la pile se purge sur place, et les plateformes déjà
   vues restent proposées pour pouvoir élargir le choix. Retenu par univers.
   Chaque plateforme est QUALIFIÉE — incluse, via une chaîne payante du hub
   (« Prime Video : via HBO Max »), ou à la location — et la carte porte
   cette indication quand un filtre est actif : une série accessible par une
   chaîne payante matchait « Prime Video » sans que rien ne le dise. La
   location ne fait jamais matcher (presque tout se loue) : elle s'indique.
   Et un filtre actif élargit la récolte des sources (×3) : il ne garde
   qu'une fraction du vivier, qui s'épuisait en quelques dizaines de gestes.
6. **« Moins de : » — le masquage de genres.** Les suggestions arrivent avec
   leurs genres ; le composant en fait des puces construites depuis la liste
   affichée (les plus fréquents d'abord, huit au plus). Cliquer barre la puce,
   purge la pile SUR PLACE et recharge sans le genre (`?sans=Animation`) ;
   la puce reste, barrée — le geste se défait où il s'est fait. Retenu par
   univers dans le navigateur. C'est un filtre de présentation : il ne touche
   ni les graines ni les scores.

**La cinquième source : les gens** *(ajoutée le 28 août 2026, sur la
question juste « les acteurs sont des relations dans Neo4j, en principe ils
contribuent ? »)*. Les relations FIV_JOUE_DANS / FIV_A_REALISE / FIV_A_CREE
existaient — les filmographies s'en servent — mais le moteur ne les
traversait pas. C'est la source qui OUVRE sur le récent : les crédits
arrivent avec la collecte, sans attendre ni notes ni membres. Une série de
2025 sans empreinte mesurée ni citation (« Le Catalogue d'Amina ») était
invisible des quatre autres sources ; par ses acteurs, elle mène à ses
consœurs de 2022-2026. Le signal sature avec le nombre de personnes
partagées (une seule est faible — un second rôle prolifique relie tout à
tout ; sept est un quasi-jumelage d'équipe), les noms partent dans
l'explication (« Avec Melissa Fumero »), et la source compte comme du
CONTENU pour la corroboration. Mesuré sur les quatre graines réelles : The
Good Place (7 personnes en commun, corroborée par la communauté), Parks and
Recreation, Machos alfa — par le créateur de Muertos S.L.

**Et le correctif qui conditionne tout le reste, trouvé sur un cas réel**
(« La Brea, Brooklyn Nine-Nine, Muertos S.L., Lucifer » rendait un mur de
séries inconnues) : **98,5 % des empreintes du graphe ne sont pas des
mesures**. 114 720 empreintes de séries sur 116 434 (519 938 sur 522 203
côté films) sont marquées `interne` — des stéréotypes déduits des
métadonnées, massivement dupliqués, votes médians de 1. « La Brea » portait
le même vecteur exact que des milliers d'œuvres obscures : ses voisins « à
distance nulle » étaient n'importe quoi. Le vectoriel — voisins de graines
ET profil — ne raisonne plus que sur les empreintes `juge` (mesurées :
1 714 séries, 2 265 films), par un balayage calculé plutôt que par l'index
k-NN, qui rendait ses plus proches parmi les clones avant tout filtre. Une
graine `interne` n'en lance pas : elle nourrit la communauté et les
affinités. Sur le même cas réel, les suggestions deviennent Psych (corroboré
par 27 voisins), iZombie, Ted Lasso, The Orville, Lupin, Warehouse 13.

**Et la pagination** *(28 août 2026, demandée avec insistance — à raison)*.
Le vivier classé (~100-600 candidats) se parcourt : `?page=2` continue
exactement où la première fenêtre s'arrête (classement déterministe, pages
disjointes), la réponse annonce `total` et `encore`. En vue liste, un
compteur « 24 sur 94 » et un bouton « Charger plus » qui AJOUTE ; la pile
passe par le même canal — quand elle s'épuise, elle demande la page
suivante au lieu de recevoir éternellement les 24 mêmes. L'ajout déduplique
par pivot : chaque geste étant une exclusion de plus, les fenêtres bougent
côté serveur.

Au passage, une boucle corrigée : une pile de trois cartes ou moins
redemandait des suggestions, recevait les mêmes, et redemandait — des
centaines de requêtes par minute, mesurées à l'écran. Le droit de recharger
ne se rouvre plus qu'à du neuf reçu ou à un geste du visiteur.

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
  projection n'en porte qu'un, celui de la collecte.
* **Le synopsis descend une cascade** : la langue demandée, puis l'anglais,
  puis la racine (collectée en `fr-FR`). L'anglais au milieu et pas en
  dernier, parce que c'est le cas courant — mesuré en lecture seule sur la
  production, sur 500 séries échantillonnées, 334 n'ont aucun synopsis à la
  racine et 325 d'entre elles en ont un en anglais. C'est le « pas de
  description » constaté, et une fiche muette faisait conclure à un catalogue
  vide. La langue retenue part dans la réponse (`synopsisLangue`) et la fiche
  la mentionne : un texte anglais servi sans le dire passerait pour une
  traduction.
* **Les filtres** sont peuplés par une agrégation sur l'index, donc par ce que
  le catalogue contient vraiment. La dimension s'adapte : genres pour les
  séries et les films, genres **et plateformes** pour eux (un livre ne se
  regarde pas sur Netflix), genres seuls pour les livres depuis que le
  crawler collecte P136.
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

## Quatre langues, un fichier

*Ajouté le 26 août 2026.*

Le site existe en **français, anglais, espagnol et arabe**, entièrement : la
coque, le contenu Markdown, le composant de suggestion, et le sens
d'écriture.

**Un seul fichier de textes**, `site/src/i18n/textes.ts`, les quatre langues
côte à côte pour chaque clé. Pas un fichier par langue : une clé traduite
trois fois sur quatre se voit en relecture de diff, elle se perd entre quatre
fichiers — et le type `Phrase` exige les quatre, donc un oubli casse le build
plutôt que la page. `site/src/i18n/langues.ts` porte la liste, les noms, le
sens (`rtl` pour l'arabe), les locales `Intl` et les chemins.

**Les URL** : le français reste à la racine (`/series`), les trois autres
langues sont préfixées (`/en/series`, `/ar/livres`). Le français n'y descend
pas — le site y est déjà indexé, et déplacer `/series` vers `/fr/series`
casserait des liens pour ne gagner qu'une symétrie. Neuf pages d'univers +
trois accueils sortent de deux routes dynamiques ; chaque page porte ses
`hreflang` et un `x-default` sur le français. Le contenu suit la même règle :
`src/content/pages/accueil.md` pour le français, `src/content/pages/en/…`
pour le reste.

**L'URL décide de la langue, seule.** Trois candidats se disputaient la
place — la préférence du navigateur, un choix retenu en `localStorage`, et la
page. Les deux premiers produisaient la même faute, vue à l'écran : arriver
sur `/ar/series` donnait une coque arabe, de droite à gauche, avec un
composant français au milieu ; et cliquer « AR » dans l'en-tête ne changeait
rien au composant, un ancien `fr` traînant dans le navigateur. Le sélecteur
de langue du composant ne modifie donc plus un état local : **il navigue**,
et tout suit d'un mouvement.

Ce qui NE se traduit pas ici : les données. Titres, genres, plateformes
viennent de l'index dans la langue demandée. Les **rôles**, eux, sortent
désormais du serveur en codes (`interpretation`, `realisation`, `creation`,
`auteur`) et les types d'offre aussi (`flatrate`, `free`…) — précisément pour
être traduits côté front plutôt que d'imposer « Interprétation » à une page
arabe.

Deux formes de pluriel seulement (juste pour trois langues sur quatre,
approché pour l'arabe qui en compte six), avec le zéro au singulier en
français : « 0 œuvre », pas « 0 œuvres ».

## Le mobile, après une capture d'écran

*Ajouté le 26 août 2026, sur une capture d'iPhone.*

Trois défauts, trois causes distinctes :

1. **Le texte de la carte du dessus passait par-dessus les affiches
   empilées.** La cause valait le détour : la carte du dessus est la seule à
   porter du texte, elle est donc plus haute que les autres ; toutes étant
   centrées sur le même point, son affiche remontait et celles du dessous se
   retrouvaient exactement derrière son texte. La réparation n'est pas un
   `z-index` mais de **sortir le texte du flux de la carte** — les cinq
   affiches ont enfin la même géométrie, et le bloc de texte vit sous elles
   sur son propre fond.
2. **La raison de la suggestion était coupée** à deux lignes derrière le ⓘ,
   s'arrêtant sur « … membres qui » : la phrase la plus utile du composant,
   illisible. Trois lignes, toute la largeur.
3. **L'outil commençait à 900 px de haut** : le héros occupait tout le premier
   écran. Sur mobile l'accroche reste, le reste passe SOUS l'outil
   (`display: contents` sur le bloc de texte réordonne ses enfants dans la
   grille, sans dupliquer un mot de HTML), et le bouton d'appel disparaît —
   il pointait vers ce qui est désormais au-dessus de lui.

Plus : l'en-tête tient à 375 px — le passage d'une langue à l'autre est un
`<details>` qui se replie sur un seul drapeau (une trentaine de pixels au
lieu de la centaine que prenaient quatre codes), et la place rendue revient
aux univers, qui sont ce qu'on vient chercher dans un en-tête. `<details>` et
non un `<select>` : le contenu reste quatre vrais liens avec leurs
`hreflang`, et le dépliement ne coûte pas une ligne de script. Un drapeau
désignant un pays et non une langue, le nom l'accompagne toujours — écrit à
côté sur grand écran, en étiquette accessible partout. Les trois pilules sur
une ligne qui glisse, et un placeholder court — le long se coupait
sur « un auteu », et les exemples ont déménagé dans le message d'accueil, où
ils tiennent.

## Ce qui reste devant

* **Le rattrapage des empreintes reste LE chantier du moteur.** L'index
  Neo4j `fivEmpreinteSource (univers, empreinteSource)` est POSÉ (27 août
  2026, autorisé) : le balayage des juges est passé de ~2 s à 134 ms, le
  moteur complet répond en 1,5 s depuis le poste. Mais élargir aux empreintes
  `interne` a été essayé et MESURÉ : même filtrées (votes ≥ 100, vecteurs non
  saturés — il en reste 1 531 côté séries, moins que les juges), leurs
  voisins ne localisent pas le goût — « La Brea » y voisine avec des
  telenovelas mexicaines, « Muertos S.L. » avec des K-dramas. La note
  scalaire prédite par l'élève est bonne (la grille l'affiche) ; l'empreinte
  par AXES `interne`, elle, ne porte pas encore un profil de goût. Tant
  qu'elle n'est pas recalculée, le vectoriel reste sur les juges.
* **Neo4j en local** : le poste n'a pas encore de Neo4j vendorisé dans ce
  module — les suggestions se testent contre le serveur ou après `make -C
  admin bootstrap-neo4j` ; le moteur, lui, est couvert par des tests
  unitaires sur faux graphe.
* **Les comptes membres** : rattacher les sessions anonymes à `membre.*`
  (import V1), et l'app React « connectée » complète.
* **BD et musiques** : entreront par `webapp/src/fiv_webapp/univers.py` et
  une entrée de contenu — nulle part ailleurs.
* **Les genres restent en français dans les quatre langues** : ce sont des
  données, collectées en `fr-FR` chez TMDB et en français chez Wikidata, donc
  une page anglaise affiche « fiction dystopique ». Les traduire demande de
  les collecter par langue à l'indexation, pas de les poser dans
  `src/i18n/textes` — un fichier d'interface n'est pas un catalogue.
* **Le sitemap et les pages de taxonomie SEO** (par origine notamment — voir
  `doc/etude-couverture-marche-arabe.md` §4) : la structure Astro les attend.
