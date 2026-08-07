# sourcing

Acquisition de données pour Fivorites V2. Aujourd'hui : les séries, via TMDB.

## Le principe

La V1 confondait collecte et dérivation : le même code appelait TMDB et écrivait
directement 45 colonnes métier. Conséquence, modifier un champ dérivé obligeait
à retélécharger 17 requêtes par série.

Ici les deux sont séparés :

```
collecte    →  raw_source   append-only, horodaté, jamais interprété
                    ↓        dérivation hors ligne, rejouable à volonté
dérivation  →  couche 1 (faits) → couche 2 (axes) → couche 3 (facettes, calculées)
```

Ce que ça change en pratique : réviser un axe de goût, ajouter une facette ou
changer de modèle de notation ne coûte plus un seul appel réseau.

Une limite à connaître : le brut protège des changements de *dérivation*, pas de
ceux de *collecte*. Ajouter un sous-appel à `SERIES_APPEND` impose de
retélécharger le catalogue. C'est pour ça que cette liste
([`client.py`](src/fiv_sourcing/sources/tmdb/client.py)) est décidée largement
et une seule fois.

## Installation (poste de dev)

Python est **vendorisé** : `make bootstrap` installe un CPython 3.12 dans
`./vendor/python` et le projet ne s'exécute que sur celui-là. Rien n'est jamais
installé globalement. `vendor/` n'est pas versionné — il se reconstruit à
l'identique depuis `.python-version` et `uv.lock`.

```bash
make bootstrap
```

### Comment la vendorisation tient

Le point faible est uv lui-même : il ne lit le répertoire de ses interpréteurs
que dans la variable `UV_PYTHON_INSTALL_DIR` — **ce n'est pas une clé de
`uv.toml`**. Un `uv run` lancé sans elle ne reconnaît pas le Python de
`vendor/`, détruit la venv et la recrée sur `~/.local/share/uv`, sans rien dire.

Trois verrous, parce qu'aucun ne suffit seul :

| Verrou | Ce qu'il empêche |
|---|---|
| Le Makefile exporte `UV_PYTHON_INSTALL_DIR` | uv trouve l'interpréteur de `vendor/` |
| **Aucune cible n'appelle `uv run`** — les outils sont invoqués dans `.venv/bin` | même si uv passait à côté du verrou 1, un `make test` ne peut pas basculer d'interpréteur |
| `make guard`, prérequis de `test`/`lint`/`doctor`/`migrate` | la dérive est détectée **avant** d'exécuter quoi que ce soit, pas après |

`uv` n'apparaît donc que dans `bootstrap` et `sync`, les deux seules cibles qui
résolvent des dépendances. Si tu dois l'appeler à la main, passe par le shim :

```bash
export PATH="$PWD/bin:$PATH"   # bin/uv force la variable, une fois par shell
```

En cas de dérive, `make guard` le dit sans ambiguïté et la réparation est
`make bootstrap`.

Puis la base — le Postgres local de la machine, pas Docker. `db-create` crée le
rôle et la base `fivorites_v2` (et ne fait rien s'ils existent), `migrate` crée
le schéma `sourcing` et ses tables :

```bash
make db-create && make migrate
```

L'équivalent en SQL de `db-create`, si tu préfères le faire à la main :

```sql
create role fivorites_v2 with login;
create database fivorites_v2 owner fivorites_v2;
```

Enfin les identifiants TMDB :

```bash
cp .env.example .env   # puis renseigner TMDB_BEARER (token v4, préférable)
```

`make doctor` vérifie les trois d'un coup.

## Utilisation

```bash
make doctor                                  # interpréteur, base, migrations, schéma, identifiants
make test                                    # 138 tests, dont 69 de bout en bout sur Postgres
```

Puis la ligne de commande, dans l'ordre où on s'en sert :

```bash
.venv/bin/fiv-sourcing tmdb export           # charge la liste de toutes les séries TMDB
.venv/bin/fiv-sourcing tmdb catalog          # volumétrie et déciles de popularité
.venv/bin/fiv-sourcing tmdb fetch --id 1399  # une série
.venv/bin/fiv-sourcing tmdb backfill         # tout le catalogue, reprenable
.venv/bin/fiv-sourcing tmdb dates            # recopie les dates du brut vers l'inventaire
.venv/bin/fiv-sourcing tmdb changes          # marque ce qui a bougé chez TMDB
.venv/bin/fiv-sourcing tmdb stats            # ce qu'il y a en base, et la projection de volume

.venv/bin/fiv-sourcing enrich --id 1399      # les sources tierces sur une série
.venv/bin/fiv-sourcing enrich                # toutes celles sans complément

.venv/bin/fiv-sourcing crawl wikidata --langue ar   # les séries hors TMDB
```

`export` ne demande aucune clé — c'est un fichier public, hors quota. `backfill`
prend `--limit`, `--concurrency`, `--order` (`id` par défaut, `random` pour
estimer une durée, `popularity`), `--refresh-after` et `--dry-run`. Il reprend là
où la passe précédente s'est arrêtée, et `changes` ne collecte rien : il pose une
marque que `backfill` transforme en recollecte.

**`enrich` n'appelle pas TMDB et ne demande donc aucun jeton.** Il entre dans
Wikidata par `P4983`, qui se déduit de l'id qu'on a déjà dans `tmdb_catalog` :
une série jamais collectée peut être enrichie. Sur *Game of Thrones*, il ramène
en 8 requêtes l'article Wikipédia des cinq langues et les résumés d'épisode
TVmaze — 258 000 caractères, là où l'overview TMDB en fait 400.

Sans `--id`, il traite **tout ce qui n'a pas encore de complément** et reprend là
où la passe précédente s'est arrêtée. Il accepte les mêmes options que
`backfill` : `--limit`, `--concurrency`, `--order`, `--refresh-after`,
`--dry-run`.

`--order recent` trie par **année de diffusion décroissante puis popularité** —
ce que la popularité seule ne fait pas, puisqu'une série de 2015 très consultée
passerait avant une nouveauté. Il demande que `tmdb dates` ait tourné : la date
vit dans le payload de la fiche, et trier 228 000 séries dessus décompresserait
toute la table. Les séries non encore collectées, qui n'ont pas de date,
partent en fin de file — ce sont aussi celles où l'enrichissement a le moins de
prise, faute d'`imdb_id` pour confirmer l'appariement TVmaze.

Le débit est **par hôte** : `ENRICH_RATE_LIMIT` (5 par défaut) vaut pour
Wikimedia, `TVMAZE_RATE_LIMIT` (2) pour TVmaze, dont la limite est documentée —
« at least 20 calls every 10 seconds per IP ». Un plafond commun ne pourrait pas
respecter l'un sans brider l'autre.

Ce qui rend cette passe tenable, c'est le **regroupement des résolutions** : une
requête SPARQL pour cent séries au lieu d'une chacune. Le catalogue entier coûte
ainsi 2 300 requêtes de résolution au lieu de 228 000 — 228 000 requêtes contre
un service gratuit et partagé ne se font pas, indépendamment du temps que ça
prendrait.

Mesuré sur 60 séries tirées au hasard du catalogue : **36 % ont un item
Wikidata**, 1,17 requête par série en moyenne, 1,7 série/s. À ce rythme, les
228 454 séries représentent environ **37 heures** et 267 000 requêtes.

**`crawl wikidata` est le flux inverse** : les séries qui existent dans Wikidata
mais pas dans TMDB. Par défaut il vise le **noyau dur** — sans identifiant TMDB
*ni* IMDb, injoignable par tout autre chemin (300 séries de langue arabe,
vérifié en réel par `--dry-run`). Il crée l'œuvre par QID (`id_tmdb` null),
conserve le brut, enrichit via Wikipédia et TVmaze, et reprend où il s'est
arrêté. Les items à `imdb_id` sont exclus par défaut — probablement des séries
TMDB non reliées, que `enrich` rattrape déjà par `P345` ; `--avec-imdb` lève
l'exclusion en connaissance de cause.

## Déploiement serveur (Docker)

**Seule l'application est conteneurisée. Postgres tourne sur l'hôte**, installé
par apt — comme en local, mais sur le serveur. Le conteneur le joint par la
passerelle du réseau Docker, dont le sous-réseau est figé dans le compose pour
que l'adresse de l'hôte (`172.28.0.1`) ne change pas au fil des recréations.

La procédure complète, une fois pour toutes :
**[`doc/serveur-debian11.md`](../doc/serveur-debian11.md)**.

Au quotidien, une fois le serveur en place :

```bash
docker compose build sourcing                    # si src/ ou migrations/ a bougé
docker compose run --rm sourcing db migrate
docker compose run --rm sourcing tmdb fetch --id 1399
```

⚠️ **Le `build` n'est pas optionnel quand une migration est arrivée.** Le
`Dockerfile` copie `migrations/` dans l'image et `MIGRATIONS_DIR` y pointe :
sans reconstruction, `db migrate` lit les migrations d'avant le `git pull` et
répond « base déjà à jour » sans rien appliquer.

Le service `sourcing` est sous le profil `cli` : c'est un pipeline par lots, pas
un service permanent, donc un `compose up` ne doit pas déclencher de collecte.
Il s'invoque à la demande avec `run --rm`.

**Sur la vendorisation dans l'image** : `vendor/` en est exclu, et c'est voulu —
le CPython vendorisé est un binaire macOS/arm64, inutilisable sous Linux. Le
principe ne change pas (un interpréteur figé, jamais « celui du système au
hasard »), seul l'ancrage change de support : en local `vendor/`, dans l'image
le tag de base. Les deux pointent la même version, tenue par `.python-version`.

Un détail qui se paie cher si on l'oublie : `uv.toml` impose
`python-preference = "only-managed"`, ce qui n'a aucun sens dans l'image, où le
seul Python disponible est celui de l'image de base. Le `Dockerfile` neutralise
ce réglage par variable d'environnement — les variables priment sur `uv.toml`,
donc le fichier reste tel quel pour le poste local.

## Structure

| Fichier | Rôle |
|---|---|
| [`http.py`](src/fiv_sourcing/http.py) | seul point de sortie réseau : limiteur, reprise, `Retry-After` |
| [`store.py`](src/fiv_sourcing/store.py) | écriture de `raw_source` et `fetch_state` |
| [`db.py`](src/fiv_sourcing/db.py) | connexion, `search_path`, migrations |
| [`sources/tmdb/client.py`](src/fiv_sourcing/sources/tmdb/client.py) | endpoints et `append_to_response` |
| [`sources/tmdb/collect.py`](src/fiv_sourcing/sources/tmdb/collect.py) | une série = la fiche + chaque saison dans chaque langue |
| [`sources/tmdb/export.py`](src/fiv_sourcing/sources/tmdb/export.py) | l'export quotidien → `tmdb_catalog` |
| [`sources/tmdb/backfill.py`](src/fiv_sourcing/sources/tmdb/backfill.py) | la collecte de masse : sélection, reprise, progression |
| [`sources/tmdb/changes.py`](src/fiv_sourcing/sources/tmdb/changes.py) | `/tv/changes` — ce que TMDB signale comme modifié |
| [`enrich.py`](src/fiv_sourcing/enrich.py) | l'enchaînement des sources tierces → `riche_source` |
| [`sources/wikidata.py`](src/fiv_sourcing/sources/wikidata.py) | le raccordement par `P4983`, et les faits |
| [`sources/wikipedia.py`](src/fiv_sourcing/sources/wikipedia.py) | l'article en entier, pas le résumé d'intro |
| [`sources/tvmaze.py`](src/fiv_sourcing/sources/tvmaze.py) | dates, épisodes, calendrier — et le protocole d'appariement |
| [`migrations/`](migrations) | le schéma, en SQL numéroté |
| [`Makefile`](Makefile) | le point d'entrée unique en local — c'est lui qui tient la vendorisation |
| [`Dockerfile`](Dockerfile) | l'image du serveur |

## Base et schémas

**Une seule base pour tout le projet — `fivorites_v2` — et un schéma par
domaine.** La collecte vit dans `sourcing` ; les couches métier (faits, axes)
auront les leurs. Ça évite l'éparpillement en bases séparées tout en gardant des
frontières nettes, et ça permet de joindre entre domaines sans dblink ni FDW.

Seul `public.schema_migrations` reste dans `public` : l'historique vaut pour la
base entière, pas pour un domaine.

La connexion pose le `search_path` une fois pour toutes, donc le code écrit
`raw_source` sans préfixe et changer de schéma reste un réglage (`DB_SCHEMA`).
Les migrations, elles, qualifient tout explicitement — c'est le seul endroit où
l'emplacement doit être sans ambiguïté. [`test_schema.py`](tests/test_schema.py)
garde le tout : une migration future qui créerait une table dans `public` par
distraction fait échouer les tests.

## Les cinq tables

`raw_source` est append-only et dédupliqué par empreinte : rejouer une collecte
sur une source inchangée n'écrit rien. `fetch_state` porte la fraîcheur par
objet — `last_fetched_at` (quand on a regardé) distinct de `last_changed_at`
(quand ça a bougé). À elles deux elles remplacent les trois fichiers JSON sur
disque qui portaient tout l'incrémental de la V1.

`tmdb_catalog` n'est pas du brut mais un **inventaire** : une ligne par série
connue de TMDB, alimentée par l'export quotidien. C'est elle qui dit ce qu'il
reste à collecter, ce qui a disparu de TMDB (`exported_on` qui décroche) et ce
qui a été signalé comme modifié (`changed_at`).

`oeuvre` est le **pivot d'identité**. Aucun identifiant universel n'existe
dehors — la moitié du Wikidata « séries » ignore TMDB, TVmaze ne porte jamais
d'id TMDB — donc on tient le nôtre : un id propre, un `univers` (les cinq
familles à venir), et les identifiants externes tous nullables et uniques.
C'est ce qui permet d'accueillir une série absente de TMDB, et de la
réconcilier le jour où elle y apparaît.

`riche_source` porte l'enrichissement, attaché au pivot par `oeuvre_id` et,
quand la série vient de TMDB, raccroché à la fiche collectée par
`raw_source_id` : une ligne par (série, source, langue), avec le texte
(`content`), les médias, les faits tiers (`facts` — pays, langue, lieux,
dates et diffuseur TVmaze, leur seul lieu de vie) et le chemin du raccordement
(`resolved_by`). **L'enrichissement n'écrit jamais dans `raw_source`** (R1 du
2026-08-07) : le brut ne porte que les références de base — la collecte TMDB,
et la référence Wikidata des séries hors TMDB écrite par le crawler. Les
`facts` sont au format canonique de
[`normalize.py`](src/fiv_sourcing/normalize.py) ; rejouer l'enrichissement,
c'est réinterroger (R4). Deux compteurs calculés,
`content_chars` et `media_count`, permettent au rapport de couverture de
seuiller sans jamais relire un article.

## Reste à faire

Le lot 3 est en place, à l'unité comme sur tout le catalogue. Restent le lot 4
(dérivation de la couche faits), le lot 5 (rapport de couverture) et les
priorités de rafraîchissement du lot 6. Voir
[`doc/v2-acquisition-series.md`](../doc/v2-acquisition-series.md).
