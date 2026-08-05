# admin

Front d'administration de Fivorites V2 : consulter ce qui a été collecté, et
suivre ce qu'il reste à collecter — par univers et **par langue**.

React + Mantine devant, FastAPI + Postgres derrière. Le module lit la base de
[`sourcing`](../sourcing) ; il ne collecte rien.

Le partage des requêtes tient en deux lignes et ne varie pas, du poste de dev au
serveur :

| Requête | Traitée par |
|---|---|
| `/api/*` | FastAPI, ici |
| tout le reste | un fichier de [`../www`](../www) |

Trois répertoires à la racine du dépôt, et il vaut mieux ne pas confondre les
deux derniers :

| Répertoire | Contenu | Suivi par git |
|---|---|---|
| **`admin/`** (ici) | l'API, les migrations, la ligne de commande | oui |
| [`front/`](../front) | les **sources** du front — React, Mantine, TypeScript | oui |
| `www/` | le **répertoire statique** — `index.html` et ses fichiers, rien d'autre | non, entièrement généré |

`vite build` lit `front/` et écrit `www/`. Sur le serveur, `www/` est monté en
volume dans le conteneur : redéployer le front ne demande ni rebuild ni push
d'image.

## Les deux vues

| Onglet | Question | Source |
|---|---|---|
| **Catalogue collecté** | « qu'est-ce qu'on a ? » — une carte par série, affiche, année, saisons | `admin.tv_card`, la projection |
| **Avancement** | « que reste-t-il à faire ? » — les 228 454 séries du catalogue, collectées ou non | `sourcing`, en direct |

Une série qui n'a pas encore été téléchargée **n'a pas de vignette** : ni
affiche, ni synopsis, ni date de diffusion — le catalogue TMDB ne porte qu'un
id, un titre original et une popularité. C'est pourquoi les deux vues existent,
et pourquoi la grille peut être vide alors que le tableau d'avancement affiche
228 454 lignes.

Le **sélecteur de langue** est commun aux deux et se trouve dans l'en-tête.
Il change trois choses :

* le compteur de couverture de chaque carte et de chaque ligne ;
* la colonne « couverture » et les filtres « présente / absente de la langue » ;
* **les synopsis d'épisode** dans la fiche d'une série — le seul endroit où la
  langue change la matière affichée et pas seulement un chiffre. Ces synopsis
  n'existent que parce que la collecte a redemandé la saison entière dans cette
  langue ; l'endpoint `translations` de TMDB ne couvre pas les épisodes.

Au clic sur une carte : la fiche complète, avec un accordéon par saison
(épisodes chargés à l'ouverture du volet), la galerie de visuels, la
distribution, et un onglet technique.

## Installation

Deux toolchains vendorisées, aucune prise au système :

```bash
make bootstrap
```

* CPython 3.12 dans `vendor/python` (version figée par `.python-version`) ;
* Node dans `vendor/node` (version figée par `.node-version`, archive vérifiée
  contre les sommes publiées par nodejs.org) ;
* `vendor/` n'est pas versionné — il se reconstruit à l'identique.

Le piège uv est le même que dans `sourcing` et se traite pareil :
`UV_PYTHON_INSTALL_DIR` n'est **pas** une clé de `uv.toml`, uv ne la lit que
dans l'environnement, et un `uv run` lancé sans elle détruit la venv
silencieusement. Trois verrous : le Makefile exporte la variable, aucune cible
n'appelle `uv run`, et `make guard` échoue avant d'exécuter quoi que ce soit.

Le piège Node est symétrique et vaut d'être connu : sur un Mac Apple Silicon,
`uname -m` répond `x86_64` si make tourne sous Rosetta, et on installerait un
Node Intel. Le Makefile interroge donc le noyau (`sysctl hw.optional.arm64`).

Puis la base — celle de `sourcing`, qui doit être migrée d'abord :

```bash
make -C ../sourcing db-create migrate   # si ce n'est pas déjà fait
make migrate                            # crée le schéma admin
```

Enfin la configuration et un compte :

```bash
cp .env.example .env       # renseigner ADMIN_SECRET_KEY (openssl rand -hex 32)
.venv/bin/fiv-admin user add sameh --name "Sameh"
```

Le mot de passe est demandé à l'invite, jamais passé en argument — une ligne de
commande finit dans l'historique du shell. `make doctor` vérifie l'ensemble.

## Utilisation

```bash
make dev          # l'API (8182) et Vite (5173) côte à côte → http://localhost:5173
make api          # l'API seule, rechargement à chaud
make web-build    # construit ../front dans ../www
make serve        # l'API sert le front → http://127.0.0.1:8182
make test         # 66 tests
make lint         # ruff + tsc
```

En développement, Vite relaie `/api` vers l'API : **une seule origine** vue du
navigateur, donc le cookie de session reste propriétaire et il n'y a rien à
configurer en CORS.

### Après une collecte

```bash
.venv/bin/fiv-admin catalog refresh
```

La grille de cartes lit une projection, pas le brut (voir plus bas). Le bouton
« Rafraîchir la projection » fait la même chose depuis le front, et un bandeau
signale d'elle-même une projection en retard.

## Déploiement serveur (Docker)

En local, rien n'est conteneurisé — Postgres et les toolchains vivent sur la
machine. Sur le serveur Debian, **tout se lance depuis Docker**, sauf Postgres
qui reste sur l'hôte (comme pour `sourcing`). Le compose est à la racine du
dépôt ; la procédure complète est dans
[`doc/serveur-debian11.md`](../doc/serveur-debian11.md) §7.

```bash
docker compose run --rm www-build            # front/ → www/ (Node jetable)
docker compose run --rm admin db migrate     # le schéma admin
docker compose run --rm -it admin user add sameh
docker compose up -d admin                   # service permanent, port 8182
```

Trois points de conception, tous vérifiables dans le compose :

* **L'image ne contient que l'API.** `www/` est un volume monté en lecture
  seule. Redéployer le front, c'est reconstruire `www/`, rien de plus.
* **Les sources ne sont montées nulle part en production.** Seul `www/` l'est,
  et il ne contient que le résultat du build : un répertoire servi en HTTP n'a
  à contenir ni code source, ni `package.json`, ni `node_modules`.
* **Node ne tourne pas en production.** Le service `www-build` est une tâche
  (profil `build`), pas un service : il construit des fichiers et s'arrête. Ce
  qui reste servi, ce sont des fichiers statiques.
* **Le port n'est publié que sur `127.0.0.1`.** Un formulaire de connexion sur
  l'internet sans TLS, c'est un mot de passe en clair sur le réseau : un tunnel
  SSH ou un reverse proxy TLS se met devant, et alors seulement
  `ADMIN_COOKIE_SECURE=true`.

## Comment c'est fait

### Les comptes

Créés en ligne de commande, jamais par le front : il n'y a pas d'inscription.
Un front d'administration qui sait fabriquer des administrateurs n'en est plus
un.

* **scrypt** pour les mots de passe — dans la bibliothèque standard, à coût
  mémoire, donc rien à installer et une résistance correcte aux attaques par
  GPU. Les paramètres sont dans la chaîne stockée : les durcir un jour ne
  cassera pas l'existant.
* **Un cookie signé** plutôt qu'un JWT. Le besoin tient en trois champs ; un
  HMAC-SHA256 sur un JSON compact fait le même travail sans bibliothèque, sans
  champ `alg` à valider et sans le piège `alg: none`. Cookie `HttpOnly` (jamais
  lisible en JavaScript) et `SameSite=Strict` (referme la falsification
  inter-site sans jeton CSRF séparé).
* **Freinage des tentatives** par couple (compte, adresse), et un compte
  inexistant répond en autant de temps qu'un mot de passe faux — sinon le délai
  de réponse dit qui existe.
* Le compte est **revérifié à chaque requête** : `fiv-admin user disable` a un
  effet immédiat, pas au bout des douze heures du jeton.

### Les lectures

Deux règles de coût, parce que le catalogue fait 228 454 séries et que le brut
en fera plusieurs millions de lignes.

**On ne touche jamais à `payload` dans une liste.** Un payload de fiche pèse des
centaines de kilooctets ; en lire cinquante par page coûterait plus cher que
tout le reste. Le nombre de saisons attendues se lit dans `fetch_state`, qui
porte une ligne par saison énumérée — succès ou échec.

**On pagine avant d'agréger.** Les jointures portent sur les identifiants de la
page courante, jamais sur le catalogue entier.

Pour la grille de cartes, ces deux règles ne suffisaient pas : trier « du plus
récent au plus ancien » porte sur une date qui vit *dans* le payload.
D'où `admin.tv_card`, une vue matérialisée qui extrait et indexe les champs de
vignette. Contrepartie assumée : elle est en retard jusqu'au prochain
`catalog refresh`. La **fiche d'une série relit toujours le brut** — ce qu'on
ouvre n'est jamais périmé.

Les index de lecture (`001_admin.sql`) portent sur les tables de `sourcing`
mais appartiennent à l'admin : c'est elle seule qui pose ces questions-là, et la
collecte n'a pas à payer leur maintenance sans savoir pourquoi.

### Ce que le front ne fait pas

**Rien ne déclenche de collecte.** L'acquisition est un traitement par lots qui
se lance en ligne de commande ; lui donner un bouton depuis une page web
reviendrait à pouvoir engager deux millions de requêtes TMDB d'un clic.

## Structure

| Fichier | Rôle |
|---|---|
| [`security.py`](src/fiv_admin/security.py) | mots de passe, jetons de session, freinage |
| [`queries.py`](src/fiv_admin/queries.py) | le tableau d'avancement — SQL et coût |
| [`catalog.py`](src/fiv_admin/catalog.py) | la grille, la fiche, les saisons |
| [`media.py`](src/fiv_admin/media.py) | les univers observables et les libellés de langue |
| [`app.py`](src/fiv_admin/app.py) | l'application FastAPI |
| [`migrations/`](migrations) | le schéma `admin` et les index de lecture |
| [`../front/src/`](../front/src) | les écrans React — voir [`front/README.md`](../front/README.md) |
| [`Dockerfile`](Dockerfile) | l'image du serveur — l'API seule, sans le front |
| [`Makefile`](Makefile) | point d'entrée unique — c'est lui qui tient les deux vendorisations |

## Limites connues

* **Les films.** Le sélecteur d'univers les propose, l'API répond qu'ils ne sont
  pas collectés — il n'existe ni inventaire ni brut pour eux. Le jour où le
  catalogue arrive, seul `catalog_table` dans [`media.py`](src/fiv_admin/media.py)
  est à renseigner.
* **Le tri par titre** suit la collation de Postgres, qui range l'écriture
  latine avant l'arabe. Il n'y a pas d'ordre alphabétique commun à deux
  alphabets, et en inventer un tromperait plus qu'il n'aiderait.
* **Le tri par dernière collecte** ne liste que ce qui a déjà été regardé (la
  jointure y devient interne). Le front l'affiche plutôt que de laisser croire à
  un catalogue amputé.
* **Le freinage des connexions est en mémoire** : remis à zéro au redémarrage,
  non partagé entre instances. Il arrête le forçage depuis une machine, pas une
  attaque distribuée.
