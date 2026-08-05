# front

Les sources du front d'administration : React, Mantine, TypeScript.

## Où va quoi

Trois répertoires, et la frontière entre eux est le point à ne pas confondre :

| Répertoire | Contenu | Suivi par git |
|---|---|---|
| [`../admin`](../admin) | l'API — FastAPI, Postgres, la ligne de commande | oui |
| **`front/`** (ici) | les **sources** du front — `src/`, `package.json`, `node_modules` | oui, sauf `node_modules` |
| [`../www`](../www) | le **répertoire statique** — `index.html` et ses fichiers, rien d'autre | oui — c'est par là que le front est déployé |

`vite build` lit ici et écrit dans `../www`. Rien d'autre ne va dans `www/` :
c'est le répertoire que FastAPI sert tel quel, et un répertoire servi en HTTP
n'a à contenir ni code source, ni `package.json`, ni `node_modules`.

**Aucun fichier ne doit être ajouté à `www/` à la main** : `emptyOutDir` le vide
à chaque build, donc tout ce qu'on y déposerait disparaîtrait au suivant. C'est
pourquoi ce README est ici et pas là-bas.

`www/` **est versionné**, lui : le build produit toujours les trois mêmes noms,
donc le suivre ne fait pas gonfler la liste des chemins, et le déploiement se
réduit à un `git pull` — aucun Node sur le serveur. En échange, un changement du
front se commite en deux morceaux :

```bash
make -C ../admin web-build        # met à jour ../www et incrémente la version
git add ../www front/package.json src/
```

Oublier le build, c'est déployer l'ancienne version sans que rien ne le signale.

Le partage des requêtes, du poste de dev au serveur :

| Requête | Traitée par |
|---|---|
| `/api/*` | FastAPI |
| tout le reste | un fichier de `www/`, à commencer par `index.html` |

## Noms fixes et numéro de version

Le build produit toujours les trois mêmes fichiers :

```
www/index.html
www/assets/index.js
www/assets/style.css
```

Pas d'empreinte du contenu dans le nom (`index-Cij1LZw0.js`) : à chaque build,
elle change, les anciens fichiers s'accumulent partout où le répertoire est
suivi ou synchronisé, et le diff d'un déploiement devient illisible.

La fraîcheur est portée autrement — par la **requête**. `index.html` référence
ses fichiers avec un numéro de version :

```html
<script type="module" src="/assets/index.js?version=0.1.2"></script>
<link rel="stylesheet" href="/assets/style.css?version=0.1.2">
```

Une URL différente est une entrée de cache différente, pour le navigateur comme
pour les intermédiaires. Le numéro est le `version` de `package.json`,
**incrémenté à chaque `vite build`** — un build modifie donc un fichier suivi par
git, et c'est le prix d'un compteur qui survit d'un build à l'autre. Un `make
dev` ne l'incrémente pas : un serveur de développement ne livre rien.

Le même numéro est injecté dans l'application (`__APP_VERSION__`) et affiché
dans le menu du compte : la version lue à l'écran est celle du bundle qui
s'exécute, pas celle que le serveur croit avoir déployé. Quand les deux
diffèrent, c'est justement ce qu'on cherche à savoir.

Ce schéma n'a de sens qu'accompagné des en-têtes de cache que pose l'API
(`VersionedStatic`, dans [`../admin/src/fiv_admin/app.py`](../admin/src/fiv_admin/app.py)) :
`no-cache` sur `index.html` pour qu'il soit revalidé à chaque fois, cache long
sur `assets/` puisque leur URL change à chaque version. Sans le premier, le
navigateur garderait l'ancienne page, continuerait à demander l'ancienne
version, et le déploiement resterait invisible.

## Développer

Tout passe par le Makefile de `admin/`, qui tient les deux toolchains
vendorisées — le CPython et le Node de `admin/vendor/`. Il n'y a pas de `npm`
système à installer, et il ne faut pas en utiliser un :

```bash
make -C ../admin bootstrap    # installe les deux toolchains et les dépendances
make -C ../admin dev          # l'API (8182) et Vite (5173) → http://localhost:5173
make -C ../admin web-build    # construit ../www
make -C ../admin lint         # ruff + tsc --noEmit
```

En développement, Vite relaie `/api` vers l'API : **une seule origine** vue du
navigateur, donc le cookie de session reste propriétaire et il n'y a rien à
configurer en CORS.

Il existe bien un service `www-build` (un conteneur Node jetable) pour
construire sur le serveur, mais **ce n'est plus le chemin normal** depuis que
`www/` est versionné — et il tourne en root, donc il laisse derrière lui des
fichiers que le `git pull` suivant ne peut plus écrire. À réserver au dépannage,
en réparant les droits ensuite :

```bash
sudo chown -R "$USER" www
```

## Les écrans

| Fichier | Rôle |
|---|---|
| [`src/App.tsx`](src/App.tsx) | deux écrans, la session décide — pas de routeur |
| [`src/components/Dashboard.tsx`](src/components/Dashboard.tsx) | l'ossature, les deux vues, l'état partagé |
| [`src/components/SeriesGrid.tsx`](src/components/SeriesGrid.tsx) | la grille de cartes et ses filtres |
| [`src/components/SeriesCard.tsx`](src/components/SeriesCard.tsx) | une vignette — affiche à gauche, l'essentiel à droite |
| [`src/components/SeriesModal.tsx`](src/components/SeriesModal.tsx) | la fiche : saisons, distribution, galerie, technique |
| [`src/components/SeasonPanel.tsx`](src/components/SeasonPanel.tsx) | les épisodes d'une saison, dans la langue choisie |
| [`src/components/AcquisitionTable.tsx`](src/components/AcquisitionTable.tsx) | le tableau d'avancement sur tout le catalogue |
| [`src/api.ts`](src/api.ts) | le seul point d'appel réseau |
| [`src/types.ts`](src/types.ts) | le contrat avec l'API |

Quelques partis pris qui se remarquent à la lecture :

* **Pas de routeur.** L'administration a une seule page ; un routeur n'y
  apporterait qu'un repli SPA à configurer côté serveur et des URL à maintenir
  pour une navigation qui n'existe pas.
* **`dir="auto"` sur tout titre venu de TMDB.** Le catalogue mêle les alphabets ;
  un titre arabe doit s'afficher de droite à gauche dans une interface en
  français, et le navigateur tranche mieux que nous sur le premier caractère
  fort.
* **Les épisodes se chargent à l'ouverture du volet**, pas avec la fiche : une
  série de huit saisons en porte deux cents, et personne ne les lit tous.
* **Les visuels viennent de `image.tmdb.org`.** On ne recopie pas une
  bibliothèque d'affiches pour l'afficher dans une page d'administration. Un
  chemin absent ou disparu tombe sur un placeholder plutôt que sur un trou.
