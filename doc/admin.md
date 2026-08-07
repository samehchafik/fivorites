# L'administration : où est le code, et ce qu'il fait

> La carte du module d'administration — les répertoires, les fichiers, les
> routes, la ligne de commande, le déploiement, et l'historique de ce qui a été
> construit. Ouvrir ce seul fichier doit suffire pour savoir **où aller**.
>
> Les détails de conception vivent dans [`admin/README.md`](../admin/README.md)
> (l'API, les comptes, le coût des lectures) et
> [`front/README.md`](../front/README.md) (le build, les écrans, l'URL). La
> façon de lire les tables du sourcing est dans
> [`contrat-donnees-admin.md`](contrat-donnees-admin.md).
>
> Rédigé le 2026-08-07.

---

## 1. Ce que c'est, en trois phrases

Un tableau de bord pour **regarder la collecte** : ce qui a été téléchargé, ce
qu'il reste à télécharger, et dans quelles langues. Il lit la base du
[`sourcing`](../sourcing) et **n'écrit jamais dedans** — il ne collecte rien, et
aucun bouton de la page web ne peut déclencher une collecte.

React + Mantine devant, FastAPI + Postgres derrière, un seul port (8182) qui
sert à la fois les fichiers et l'API.

## 2. Où est le code

Trois répertoires à la racine du dépôt. La frontière entre les deux derniers est
le point qu'on confond une fois, et une seule :

| Répertoire | Contenu | Qui l'écrit |
|---|---|---|
| [`admin/`](../admin) | l'API FastAPI, les migrations, la ligne de commande, les tests | à la main |
| [`front/`](../front) | les **sources** React — `src/`, `package.json`, `vite.config.ts` | à la main |
| [`www/`](../www) | le **répertoire servi** — `index.html`, `assets/index.js`, `assets/style.css` | `vite build`, jamais à la main |

`www/` est **versionné** : c'est ce qui permet de déployer le front par un
simple `git pull`, sans Node sur le serveur. Il ne contient que trois fichiers,
toujours les mêmes noms — donc le suivre ne fait pas gonfler le dépôt.

```
admin/
├── src/fiv_admin/
│   ├── app.py              l'application FastAPI, les en-têtes de cache, le montage de www/
│   ├── config.py           les réglages (variables d'environnement)
│   ├── db.py               le pool psycopg, le cycle de vie des connexions
│   ├── deps.py             les dépendances FastAPI : connexion, utilisateur courant
│   ├── security.py         scrypt, cookie signé, freinage des tentatives
│   ├── queries.py          l'avancement : le SQL du tableau et son coût
│   ├── catalog.py          la grille de cartes, la fiche, les saisons, la projection
│   ├── media.py            les univers observables et les libellés de langue
│   ├── redact.py           le masquage des secrets dans les journaux
│   ├── cli.py              la ligne de commande `fiv-admin`
│   └── routes/
│       ├── auth.py         /api/login, /api/logout, /api/me
│       ├── acquisition.py  /api/meta, /api/acquisition/*
│       └── catalog.py      /api/catalog/*
├── migrations/             001 le schéma admin + index, 002 la vue matérialisée
├── tests/                  91 tests
├── Dockerfile              l'image du serveur — l'API seule, sans le front
└── Makefile                point d'entrée unique, tient les deux toolchains vendorisées

front/src/
├── App.tsx                 deux écrans, la session décide — pas de routeur
├── api.ts                  le seul point d'appel réseau
├── types.ts                le contrat avec l'API
├── display.ts              les fonctions d'affichage (nombres, durées, images TMDB)
├── urlState.ts             l'état partageable : ?id= ?lang= ?filtre=
└── components/
    ├── Dashboard.tsx       l'ossature, les deux vues, l'état partagé
    ├── LoginPage.tsx       le formulaire de connexion
    ├── LanguagePicker.tsx  le sélecteur de langue de l'en-tête
    ├── SummaryCards.tsx    les chiffres de tête
    ├── SeriesGrid.tsx      la grille de cartes et ses filtres
    ├── SeriesCard.tsx      une vignette — affiche à gauche, l'essentiel à droite
    ├── SeriesModal.tsx     la fiche : saisons, distribution, galerie, technique
    ├── SeasonPanel.tsx     les épisodes d'une saison, dans la langue choisie
    ├── WatchPanel.tsx      où regarder la série, dans le pays de la langue
    ├── AcquisitionTable.tsx le tableau d'avancement sur tout le catalogue
    ├── LanguageCoverage.tsx la couverture par langue
    ├── DetailDrawer.tsx    le détail d'une ligne d'avancement
    ├── Filters.tsx         les filtres du tableau
    └── Boundary.tsx        le filet : une erreur de rendu explique le décalage de version
```

## 3. Le chemin d'une requête

Il ne varie pas, du poste de développement au serveur :

| Requête | Traitée par |
|---|---|
| `/api/*` | FastAPI |
| tout le reste | un fichier de `www/`, à commencer par `index.html` |

Une seule origine, donc : le cookie de session reste propriétaire et il n'y a
rien à configurer en CORS. En développement, Vite (5173) relaie `/api` vers
l'API (8182) pour préserver exactement cette propriété.

Les en-têtes de cache sont posés par `VersionedStatic`
([`app.py`](../admin/src/fiv_admin/app.py)) : `no-cache` sur `index.html` pour
qu'il soit revalidé à chaque fois, cache long sur `assets/` puisque leur URL
change à chaque version (`?version=0.1.37`).

## 4. Ce qu'on voit à l'écran

### Les deux vues

| Onglet | Question | Source |
|---|---|---|
| **Catalogue collecté** | « qu'est-ce qu'on a ? » — une carte par série | `admin.tv_card`, la projection |
| **Avancement** | « que reste-t-il à faire ? » — les 228 454 séries du catalogue | `sourcing`, en direct |

Une série non téléchargée **n'a pas de vignette** : le catalogue TMDB ne porte
qu'un id, un titre original et une popularité. C'est pourquoi les deux vues
existent, et pourquoi la grille peut être presque vide alors que le tableau
affiche 228 454 lignes.

### La grille

Cartes triées, filtrées, paginées. Deux critères de tri combinables (date,
année, note, popularité, titre, dernière collecte), deux cases (« avec affiche », « avec
descriptif »), une recherche, un seuil de popularité. Le décompte affiche
`filtrés / total` dès qu'un filtre est en place.

Le tri **par note** est pondéré par le nombre de votants — moyenne bayésienne,
cinquante votes fictifs à 6,5. Sur la note brute, la tête de liste n'est faite
que de séries notées 10 par une personne ; ici il faut du volume pour s'écarter
de la moyenne. Une série sans aucun vote vaut `null` et part en fin de liste
dans les deux sens : elle n'est pas mal notée, elle n'est pas notée.

### La fiche

Au clic sur une carte, en fenêtre : **où regarder la série** (par pays), un
accordéon par saison — les épisodes ne se chargent qu'à l'ouverture du volet,
une série de huit saisons en porte deux cents —, la galerie de visuels, la
distribution, et un onglet technique. Un clic sur n'importe quelle image
l'agrandit en 800 × 600.

Deux flèches en haut de la fenêtre passent à l'œuvre précédente ou suivante,
**dans l'ordre affiché par la grille** — tri, second critère et filtres
compris — avec le rang courant à côté (« 37 / 1 240 »). Aux bords de la page
elles changent de page : la pagination est une commodité d'affichage, pas une
frontière que l'utilisateur ait à connaître. Une fiche ouverte par `?id=` sans
que la grille la contienne n'a pas de flèches, faute de voisines à désigner.

### La langue

Le sélecteur est dans l'en-tête **et** dans la fiche : c'est le même état, pas
une copie. Il change cinq choses :

* le compteur de couverture de chaque carte et de chaque ligne ;
* **le pays** dont on affiche les plateformes de streaming ;
* la colonne « couverture » et les filtres « présente / absente de la langue » ;
* **le titre, l'accroche et le synopsis** — dans la grille comme dans la fiche ;
* **les synopsis d'épisode**, seul endroit où la langue change la matière et pas
  seulement un chiffre.

Quand la traduction manque, le titre original est affiché plutôt que le français
— sauf si la langue demandée *est* le français. Laisser croire à une collecte
complète serait le contraire de ce que ce tableau de bord mesure.

### L'URL

```
?id=1399                            ouvre la fiche de la série 1399
?lang=ar-SA                         choisit la langue
?filtre=image,description           coche les deux cases et applique les filtres
?tri=note:desc&puis=popularite:desc les deux critères de tri, et leur sens
?id=1399&onglet=training1           ouvre la fiche directement sur l'atelier Training 1
```

Les noms se tapent comme ils se lisent (`date`, `annee`, `titre`, `note`,
`popularite`, `collecte`), le sens est facultatif — `?tri=note` vaut
`?tri=note:desc` —, une valeur inconnue est ignorée plutôt que transmise, et
`?puis=aucun` retire le départage que le défaut applique.

L'URL est la source au chargement, puis l'état la réécrit : une adresse collée
dans une conversation rouvre exactement la même vue, cases cochées comprises.

## 5. L'API

Onze routes pour le suivi de la collecte, plus `/api/health` que le healthcheck
de Docker interroge. Toutes exigent la session, sauf ces deux-là. L'atelier
d'entraînement de la notation ajoute les siennes sous `/api/training`.

| Route | Rôle |
|---|---|
| `POST /api/auth/login` | ouvre la session (cookie signé, `HttpOnly`, `SameSite=Strict`) |
| `POST /api/auth/logout` | la referme |
| `GET /api/auth/me` | le compte courant — revérifié en base à chaque requête |
| `GET /api/meta` | les langues, les univers, les tris disponibles |
| `GET /api/acquisition/summary` | les chiffres de tête (cache serveur d'une minute) |
| `GET /api/acquisition/items` | le tableau d'avancement — `lang`, `media`, `status`, `search`, `sort`, `page` |
| `GET /api/acquisition/items/{id}` | le détail d'une ligne |
| `GET /api/catalog/cards` | la grille — `lang`, `sort`/`sort2`, `withPoster`, `withOverview`, `page` |
| `GET /api/catalog/works/{id}` | la fiche complète, relue **dans le brut** |
| `GET /api/catalog/works/{id}/seasons/{n}` | les épisodes d'une saison, dans la langue demandée |
| `POST /api/catalog/refresh` | recalcule la projection `admin.tv_card` |

Chaque page de la grille embarque l'état de la projection : une grille vide a
deux causes très différentes — rien de collecté, ou une projection jamais
rafraîchie — et le front doit pouvoir les distinguer.

## 6. La ligne de commande

`fiv-admin`, installée par `make bootstrap` dans `admin/.venv/bin` :

| Commande | Rôle |
|---|---|
| `serve` | lance l'API |
| `doctor` | vérifie la base, le schéma, la configuration, le front |
| `db migrate` | applique les migrations du schéma `admin` |
| `user add <login>` | crée un compte — **le mot de passe est demandé à l'invite** |
| `user passwd <login>` | le change |
| `user disable <login>` | le désactive — effet immédiat, pas au bout des 12 h du jeton |
| `user list` | les liste |
| `catalog refresh` | recalcule la projection |
| `training note -n <N>` | note les N séries les plus populaires pas encore jugées |

`training note` est le remplissage de la phase 1 : la page Training note une
œuvre à la fois, ce que soixante œuvres rendent intenable. Elle emprunte
exactement le même chemin — même dossier, mêmes juges, même journal — et saute
les œuvres déjà notées sur le barème, si bien que relancer continue le lot au
lieu de le refaire. C'est un appel payant par œuvre : `--apercu` montre la
liste et l'ordre de grandeur du coût sans rien appeler.

```bash
docker compose run --rm admin training note -n 50 --apercu   # ce qu'on s'apprête à payer
docker compose run --rm admin training note -n 50            # puis pour de vrai
```

« Pas encore jugées » se lit dans `notation.training_run` : une œuvre qui a
déjà un essai sur le barème est écartée, quel que soit son contenu — c'est le
journal que l'atelier affiche, et proposer une œuvre déjà visible comme notée
à l'écran serait incompréhensible. Et cela s'entend **sur le barème courant** : l'entraînement des
poids filtre par version, donc une note rendue sous un barème précédent ne
nourrit pas le suivant. Une œuvre déjà vue en v1 revient donc dans la liste
pour v2, avec la mention « déjà v1 » pour que ça se lise. `--inedites`
restreint aux œuvres jamais jugées, quand on cherche à élargir le catalogue
plutôt qu'à compléter un barème.

La liste exige une **affiche** ; `--sans-filtre` lève cette condition. Le
descriptif n'entre pas dans le filtre : le champ est présent ou absent selon la
langue interrogée, donc mal calibré pour trancher — c'est la taille du dossier
assemblé qui décide en aval.

L'ordre est celui du catalogue — popularité, puis note des votants. Ce n'est
pas un biais de confort : les œuvres les plus vues ont les dossiers les plus
fournis (Wikipédia, synopsis d'épisodes, visuels), donc apprennent le plus par
appel payé. La longue traîne viendra quand le barème tiendra.

Il n'y a **pas d'inscription** depuis le front : un front d'administration qui
sait fabriquer des administrateurs n'en est plus un. Et le mot de passe n'est
jamais un argument de commande — une ligne de commande finit dans l'historique
du shell.

### Créer le compte, ou réinitialiser son mot de passe

Sur le serveur, en conteneur :

```bash
docker compose run --rm -it admin user add admin --name "Admin"
docker compose run --rm -it admin user passwd admin     # réinitialiser
docker compose run --rm admin user list
```

En local, la même commande sans Docker : `admin/.venv/bin/fiv-admin user add admin`.

Quatre points qui font perdre du temps quand on les ignore :

* **`-it` est obligatoire** pour `add` et `passwd` : sans terminal attaché,
  l'invite de mot de passe n'a nulle part où s'afficher ;
* le mot de passe est demandé **deux fois** et fait **12 caractères minimum** ;
* `add` sur un compte existant n'écrase rien — il renvoie vers `passwd`, qui est
  la réinitialisation. Il n'y a pas de « mot de passe oublié » par courriel ;
* un compte désactivé se rouvre par `user disable admin --enable`.

Le nom du schéma, lui, **n'est pas un réglage** : les migrations posent `admin`
en dur. Un `ADMIN_SCHEMA` différent dans l'environnement ferait chercher les
comptes dans un schéma que rien ne créera — le compose ne transmet plus cette
variable, et la commande le dit si elle la trouve quand même.

## 7. La base

Le module possède son schéma `admin` et rien d'autre :

| Objet | Migration | Rôle |
|---|---|---|
| `admin.admin_user` | 001 | les comptes — login, hash scrypt, état |
| quatre index sur `sourcing` | 001 | les questions que seule l'admin pose |
| `admin.tv_card` | 002 | la vue matérialisée des vignettes |

Les index posés sur les tables du sourcing appartiennent quand même à l'admin :
c'est elle seule qui pose ces questions-là, et la collecte n'a pas à payer leur
maintenance sans savoir pourquoi.

`admin.tv_card` existe parce que trier « du plus récent au plus ancien » porte
sur une date qui vit *dans* le payload, et qu'aucune liste ne doit lire un
payload (une fiche pèse des centaines de kilooctets). Contrepartie assumée : la
projection est en retard jusqu'au prochain `catalog refresh`, et un bandeau le
signale. **La fiche, elle, relit toujours le brut** — ce qu'on ouvre n'est
jamais périmé.

## 8. Développer

Tout passe par le Makefile de `admin/`, qui tient les deux toolchains
vendorisées — CPython 3.12 et Node, dans `admin/vendor/`, non versionnés et
reconstruits à l'identique. Il n'y a pas de `npm` ni de `python` système à
installer, et il ne faut pas en utiliser un.

```bash
make -C admin bootstrap    # les deux toolchains et les dépendances
make -C admin migrate      # le schéma admin
make -C admin db-create    # la base de test, propre à l'admin
make -C admin dev          # l'API (8182) + Vite (5173) → http://localhost:5173
make -C admin test         # 91 tests
make -C admin lint         # ruff + tsc --noEmit
make -C admin web-build    # construit front/ dans www/ et incrémente la version
```

Un changement du front se commite en **deux morceaux** : les sources et le
build. Oublier `web-build`, c'est déployer l'ancienne version sans que rien ne
le signale.

## 9. Déployer

Sur le serveur Debian, tout tourne dans Docker sauf Postgres, qui reste sur
l'hôte. Deux moitiés qui se déploient séparément — c'est la seule chose à
retenir :

| Ce qui change | Ce qu'on lance |
|---|---|
| le front (`www/`) | `git pull` |
| l'API (`admin/`) | `git pull && docker compose build admin && docker compose up -d admin` |

```bash
docker compose run --rm admin db migrate       # après une migration
docker compose run --rm -it admin user add sameh
docker compose up -d admin                     # service permanent, port 8182
```

Le dépôt du serveur est une copie de déploiement : il ne doit **jamais** porter
de modification locale, sans quoi le `git pull` suivant refuse de démarrer. La
remise à plat est `git fetch origin && git reset --hard origin/main`.

Le port est publié sur `0.0.0.0` (réglable par `ADMIN_BIND`). Tant qu'il n'y a
pas de TLS devant, **le mot de passe de connexion et le cookie de session
circulent en clair**. Avec un reverse proxy TLS : `ADMIN_BIND=127.0.0.1` et
`ADMIN_COOKIE_SECURE=true`.

## 10. Ce qui a été fait, dans l'ordre

Chaque ligne est un ou plusieurs commits ; `git log -- admin front www` donne le
détail.

| Lot | Ce qui a été construit |
|---|---|
| **Le socle** | l'API FastAPI, le schéma `admin`, les comptes scrypt + cookie signé, le tableau d'avancement par langue, les deux toolchains vendorisées |
| **La séparation des répertoires** | `front/` pour les sources, `www/` pour le build — un répertoire servi en HTTP n'a à contenir ni code source ni `node_modules` |
| **Les noms de fichiers fixes** | plus d'empreinte dans le nom ; la fraîcheur passe par `?version=x.y.z`, incrémenté à chaque build, affiché dans l'application |
| **Le déploiement Docker** | l'image ne contient que l'API, `www/` est un volume en lecture seule qui arrive par git ; le service qui construisait sur le serveur a été retiré — il écrivait dans des fichiers suivis et cassait le `git pull` suivant |
| **La grille de cartes** | `admin.tv_card`, le tri par date, la fiche complète en fenêtre, l'accordéon des saisons, la galerie, la distribution |
| **Où regarder la série** | les plateformes par pays, déjà collectées par le sourcing et simplement pas lues |
| **Les tris et les filtres** | second critère de tri combinable, filtres « avec affiche » et « avec descriptif », décompte `filtrés / total` |
| **L'URL partageable** | `?id=`, `?lang=`, `?filtre=` — l'URL est la source au chargement, puis l'état la réécrit |
| **Les langues** | la fiche, les épisodes **et** les vignettes de la grille dans la langue choisie, en résolvant les traductions champ par champ comme le fait TMDB ; repli sur le titre original, jamais sur le français |
| **La mesure du retard** | le bandeau « série(s) collectée(s) depuis le dernier calcul » compte contre le brut, plus contre `fetch_state` — qui déclarait des succès sans aucune ligne collectée |
| **Le filet** | une erreur de rendu affiche la cause probable (front et API de versions différentes) au lieu d'une page blanche |
| **Les derniers gestes** | le sélecteur de langue dans la fiche, l'agrandissement des photos en 800 × 600 |

## 11. Ce qui n'est pas fait

* **Les films.** Le sélecteur d'univers les propose, l'API répond qu'ils ne sont
  pas collectés. Le jour où le catalogue arrive, seul `catalog_table` dans
  [`media.py`](../admin/src/fiv_admin/media.py) est à renseigner.
* **`riche_source` n'est pas exposée.** L'enrichissement (articles Wikipédia,
  faits canoniques) existe en base mais aucun écran ne le montre.
* **Le tri par titre** suit la collation de Postgres, qui range le latin avant
  l'arabe. Il n'y a pas d'ordre alphabétique commun à deux alphabets.
* **Le freinage des connexions est en mémoire** : remis à zéro au redémarrage,
  non partagé entre instances. Il arrête le forçage depuis une machine, pas une
  attaque distribuée.
* **Pas de TLS**, tant qu'aucun reverse proxy n'est devant — voir §9.
