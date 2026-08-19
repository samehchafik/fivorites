# Le graphe Neo4j — modèle, décisions, mise en service

Écrit le 2026-08-19, à l'ouverture de la phase 1 de
[`plan-apres-notation.md`](plan-apres-notation.md) : « livrer, plutôt
qu'améliorer ». La notation existe — 502 œuvres jugées, une régression à 0,84
de MAE sur la traîne. L'inventaire existe — 228 953 séries et 1 231 681 films.
Il manquait l'espace où l'un rencontre l'autre.

Ce document dit **ce qui est en place**, et surtout **pourquoi c'est modélisé
ainsi**. Le code est dans [`admin/src/fiv_admin/graphe.py`](../admin/src/fiv_admin/graphe.py) ;
il ne répète pas ces raisonnements, il les applique.

---

## 1. Le modèle en une image

```
                    ┌─────────────────────────┐
   FIV_A_POUR_GENRE │      :FivOeuvre         │
      ┌────────────►│      :FivSerie          │
      │             │   (ou :FivFilm)         │
┌───────────┐       │                         │
│ :FivGenre │       │ oeuvreId ← le pivot     │
│ cle: …    │       │ univers, idTmdb         │
│ nom: Drame│       │ titre, annee, affiche   │
└───────────┘       │ note, votes             │
                    │                         │
┌──────────────┐    │ empreinte ────────► index vectoriel euclidien
│ :FivPersonne │    │ empreinteUnitaire ► index vectoriel cosinus
│ cle: tmdb:…  │    │ empreinteNorme            │
│ nom, photo   │    │ empreinteSource, Bareme   │
└──────┬───────┘    └─────────────────────────┘
       │                       ▲
       │  FIV_JOUE_DANS {personnage, ordre, épisodes}
       │  FIV_A_REALISE {épisodes}
       └───  FIV_A_CREE  ──────┘
```

**Tout porte le préfixe `Fiv`** — labels et types de relation. Neo4j n'a pas de
schémas comme Postgres : une base est un seul espace de noms. Le préfixe est le
seul moyen de dire « ceci est à nous », et le jour où la même instance porte un
import tiers, un plugin ou une expérimentation, `MATCH (n:FivOeuvre)` reste
exact.

---

## 2. Les trois décisions de modélisation

### 2.1 L'univers est un **label**, pas une relation

C'était la question ouverte : `movie|tv` en relation, ou en propriété du nœud ?
**Ni l'un ni l'autre exactement — en label**, avec la propriété en doublure.

Le nœud porte `:FivOeuvre` *et* `:FivFilm` (ou `:FivSerie`), plus une propriété
`univers`.

Contre la relation vers un nœud d'univers : ce serait un **supernœud**. Un
million deux cent mille films pointant sur un unique `(:FivUnivers {nom:
'film'})`. Chaque traversée qui y passe doit dérouler un million de relations,
et le planificateur de Neo4j ne peut rien faire de mieux. Or ce nœud ne répond
à aucune question réelle : « les autres films », c'est le catalogue entier.
Personne ne le demande.

Pour le label : c'est l'outil natif du moteur pour exactement ce cas. Un
balayage par label est une opération de premier ordre — Neo4j tient un index de
labels — et `MATCH (o:FivOeuvre:FivFilm)` ne coûte rien.

Le genre, lui, **est** une relation, et c'est le contre-exemple qui éclaire la
règle : « les autres drames » est une question qu'on pose vraiment, et le
nombre de genres (une vingtaine) fait des nœuds fréquentés mais utiles.

La propriété `univers` reste, en plus du label : **le label sert au moteur, la
propriété sert au retour vers Postgres**. Une route qui rend un résultat doit
pouvoir écrire `univers` sans traduire un label, et l'index composite
`(univers, idTmdb)` a besoin de la propriété.

### 2.2 L'identité est le **pivot**, jamais l'identifiant TMDB

`oeuvreId` est `sourcing.oeuvre.id`, la clé primaire du pivot de la couche 1.
Deux raisons, toutes deux déjà payées ailleurs dans ce projet :

1. **Les identifiants TMDB se chevauchent entre univers.** `1399` désigne *Game
   of Thrones* côté `/tv` et un tout autre film côté `/movie`. C'est ce qui a
   motivé la migration `sourcing/012_univers.sql`, et un graphe clé par `idTmdb`
   referait la même faute en pire — silencieusement, en fusionnant deux œuvres.
2. **Toutes les œuvres n'ont pas d'identifiant TMDB.** 300 des 480 séries de
   langue arabe n'ont aucun identifiant externe. Le pivot existe précisément
   pour elles.

Genres et personnes, eux, n'ont **pas encore** de pivot en Postgres. Leur clé
est celle de la source, préfixée par elle : `tmdb:18`, `tmdb:22970`. Le préfixe
n'est pas décoratif — le jour où un genre vient de Wikidata ou d'un référentiel
de livres, les deux espaces de numéros se croiseraient. Et c'est une **dette
assumée** : le jour où une personne doit être réconciliée entre TMDB et Wikidata,
c'est une table `sourcing.personne` qu'il faut, pas une astuce dans le graphe.

### 2.3 Ce que le nœud porte, et ce qu'il ne porte pas

Le principe est celui d'`search.py` : *le graphe rend des identifiants classés,
Postgres hydrate la page.* Le nœud porte donc le minimum pour **filtrer, classer
et afficher une vignette sans second aller-retour** — titre, année, affiche,
note pondérée, empreinte — et rien de plus. Pas de synopsis, pas de saisons, pas
de disponibilité par plateforme : tout ça vit dans `raw_source` et n'a aucune
raison d'être dupliqué dans un moteur de traversée.

La note est la **moyenne bayésienne** de `catalog.py`, jamais `popularity` : le
dictionnaire de données disqualifie cette dernière (biais occidental mesuré,
facteur 6 contre l'écriture arabe), et un graphe qui la porterait l'importerait
dans chaque classement.

---

## 3. L'empreinte, et les deux distances

C'est le point qui demandait le plus d'attention, et il en a demandé deux.

### 3.1 Le vecteur

Six coordonnées — joie, tristesse, peur, rêve, réflexion, action pour le barème
`empreinte-v3` — chacune de 1 à 10. **L'ordre des coordonnées est celui du
tableau `axes` du barème**, lu en base, jamais l'ordre alphabétique. C'est le
contrat qui rend deux vecteurs comparables, et il est vérifié par un test
d'intégration.

Trois conséquences directes :

- **Le barème définit l'espace.** Changer de barème n'est pas une variante,
  c'est un autre espace. Les index vectoriels portent donc la dimension du
  barème sous lequel ils ont été posés, et Neo4j refuse d'indexer un vecteur
  d'une autre taille — le désaccord se voit à l'écriture, pas dans un classement
  silencieusement faux.
- **Un vecteur incomplet n'est pas un vecteur.** Une œuvre notée sur cinq axes
  sur six entre dans le graphe **sans empreinte**. Boucher le trou par un zéro
  ou par la moyenne la déplacerait dans l'espace sans que rien ne le signale.
- **Le juge et la régression ne se mélangent jamais dans un même vecteur.** La
  ridge contracte vers la moyenne (pente mesurée de 0,49 à 0,68) : ses
  coordonnées ne sont pas à la même échelle que celles du juge. Le juge prime,
  la régression sert de repli, et `empreinteSource` garde la trace sur le nœud.

Ce dernier point n'est pas cosmétique. Le §5.2 de
[`mission-empreinte-culturelle.md`](mission-empreinte-culturelle.md) réclame un
contrôle explicite — *la dispersion des empreintes prédites est-elle comparable
à celle des empreintes notées ?* — parce qu'une erreur moyenne faible avec une
dispersion écrasée est le pire des cas et qu'aucune métrique d'erreur ne le
signale. `empreinteSource` est ce qui rendra ce contrôle calculable d'une
requête.

### 3.2 Deux index, parce qu'il y a deux questions

| index | propriété | métrique | la question |
|---|---|---|---|
| `fivEmpreinteVoisins` | `empreinte` | euclidienne | **le plus proche**, au sens GPS |
| `fivEmpreinteCouleur` | `empreinteUnitaire` | cosinus | **la même couleur**, intensité mise de côté |

Le projet avait tranché pour le **cosinus** (§5.1 de la mission empreinte) :
sur des composantes d'un mélange, c'est la direction qui porte le goût, et
c'est cette similarité que le profil d'un membre interrogera.

Mais le même document, au §5.4, notait la limite en toutes lettres : *« deux
œuvres de même couleur mais d'intensité différente auront une similarité cosinus
de 1. Si l'on veut distinguer un peu de peur de beaucoup de peur, il faudra
réintroduire la norme comme critère secondaire — c'est faisable, mais c'est une
décision à prendre consciemment plutôt qu'à découvrir. »*

**Elle est prise ici, et de deux façons.** `empreinteNorme` est sur le nœud,
filtrable et triable. Et l'index euclidien existe, parce que la distance
euclidienne sur des notes de 1 à 10 a une propriété que le cosinus n'a pas :
**elle se lit en points de note**. Une distance de 0,8 entre deux œuvres, c'est
l'ordre de grandeur du MAE du système (0,84). Dire « ces deux œuvres sont plus
proches que la précision de notre mesure » est une phrase qui a un sens, et
c'est le genre de phrase qui empêche de survendre une recommandation.

Un index vectoriel Neo4j ne porte qu'une métrique — d'où deux propriétés pour
deux index. Le coût est de six flottants par nœud. Cosinus sur le vecteur
unitaire et cosinus sur le vecteur brut donnent exactement le même classement :
rien n'est perdu, et la normalisation devient inspectable.

**La quantification est désactivée**, et ce n'est pas un détail : Neo4j quantifie
par défaut (`vector.quantization.type: 'scalar'`). C'est fait pour des
embeddings de 1 536 dimensions qu'on veut faire tenir en mémoire. Ici le vecteur
en a six : il n'y a rien à économiser, et arrondir six nombres qui portent tout
le sens du classement, c'est payer une perte de précision contre rien.

### 3.3 Les requêtes que ça donne

Tout ce qui suit a été exécuté contre un Neo4j 2026.07.1 réel, sur quatre
œuvres d'essai, avant d'être écrit ici.

**Sur la forme.** On appelle `db.index.vector.queryNodes()`, et pas la clause
`SEARCH … IN (VECTOR INDEX …)` qui la remplace. Raison mesurée : la clause
`SEARCH` existe bien en 2026.07 mais **appartient à Cypher 25**, alors que le
serveur interprète par défaut en Cypher 5 — sans préfixe `CYPHER 25`, le
parseur répond `Invalid input 'SEARCH'`. La procédure, elle, marche sans rien
demander, et marche aussi sur la LTS 5.26. Elle est marquée dépréciée depuis
2026.04, pas retirée ; le jour où le défaut passera à Cypher 25, la bascule
sera une réécriture de trois requêtes.

Les cinq œuvres les plus proches d'une autre, au sens GPS :

```cypher
MATCH (source:FivOeuvre {oeuvreId: $pivot})
CALL db.index.vector.queryNodes('fivEmpreinteVoisins', 6, source.empreinte)
YIELD node AS voisine, score
WHERE voisine <> source
RETURN voisine.titre, round(sqrt(1.0 / score - 1.0), 3) AS ecart
```

`score` est borné 0..1 et vaut `1/(1+d²)` : `sqrt(1/score - 1)` rend la distance
en points de note. Comparer cet écart à 0,84 — le MAE du système — dit si la
proximité est réelle ou dans le bruit. Sur le jeu d'essai, une quasi-jumelle
sort à **0,424** (donc sous le bruit : indiscernables), et une œuvre lumineuse
à **12,6**.

La même couleur, intensité mise de côté :

```cypher
MATCH (source:FivOeuvre {oeuvreId: $pivot})
CALL db.index.vector.queryNodes('fivEmpreinteCouleur', 50, source.empreinteUnitaire)
YIELD node AS voisine, score
WHERE voisine <> source AND voisine.empreinteNorme > source.empreinteNorme
RETURN voisine.titre, score, voisine.empreinteNorme
ORDER BY score DESC LIMIT 5
```

**C'est ici que les deux index se séparent, et la mesure le montre.** Une œuvre
d'essai construite comme la première × 0,4 — même direction, intensité bien
moindre — sort à **8,005** de distance euclidienne, et à **1,0000** de
similarité cosinus. Le §5.4 de la mission empreinte annonçait exactement ça en
prose ; les deux index en font deux réponses distinctes plutôt qu'un
compromis, et `empreinteNorme` permet de trancher dans un sens ou dans l'autre.

Et ce que le vecteur seul ne sait pas faire — la zone donnée par l'empreinte,
départagée par le graphe :

```cypher
MATCH (source:FivOeuvre {oeuvreId: $pivot})
CALL db.index.vector.queryNodes('fivEmpreinteCouleur', 200, source.empreinteUnitaire)
YIELD node AS voisine, score
WHERE voisine <> source
MATCH (source)-[:FIV_A_POUR_GENRE]->(:FivGenre)<-[:FIV_A_POUR_GENRE]-(voisine)
OPTIONAL MATCH (source)<-[:FIV_JOUE_DANS|FIV_A_REALISE|FIV_A_CREE]-(p:FivPersonne)
              -[:FIV_JOUE_DANS|FIV_A_REALISE|FIV_A_CREE]->(voisine)
RETURN voisine.titre, score, count(DISTINCT p) AS liens
ORDER BY score DESC, liens DESC LIMIT 10
```

*« Le vecteur dit où chercher, le graphe dit quoi prendre »*
([`v2-notation-axes.md`](v2-notation-axes.md) §5.3) — c'est cette requête.

## 4. La distribution : ce qui entre, ce qui reste dehors

| relation | source TMDB | direction |
|---|---|---|
| `FIV_JOUE_DANS` | `aggregate_credits.cast`, sinon `credits.cast` | personne → œuvre |
| `FIV_A_REALISE` | `credits.crew` job `Director` (films) ; `aggregate_credits.crew` département `Directing` filtré sur le métier `Director` (séries) | personne → œuvre |
| `FIV_A_CREE` | `created_by` | personne → œuvre |

Trois plafonds, tous délibérés :

- **15 acteurs par œuvre.** TMDB rend la distribution dans l'ordre du générique
  et la queue en est le figurant crédité d'une réplique. Au-delà d'une
  quinzaine, on n'ajoute pas de signal : on fabrique des supernœuds — un acteur
  de complément relie entre elles des centaines d'œuvres sans rapport, et chaque
  traversée par les personnes doit ensuite l'écarter.
- **10 réalisateurs par série, les plus présents.** Un film a un réalisateur.
  Une série de trois cents épisodes en a quatre-vingts, dont soixante ont dirigé
  un unique épisode.
- **`FIV_A_CREE` n'existe que pour les séries**, et c'est le vrai pendant du
  réalisateur de film : sur une série, c'est le créateur qui porte l'intention,
  pas le réalisateur du sixième épisode de la saison 3.

`aggregate_credits` prime sur `credits` pour les séries : le second ne rend que
le casting de la saison 1, ce qui est le genre d'erreur qu'on ne voit qu'en
comparant deux fiches.

---

## 5. Unicité : une personne, un nœud

C'est la garantie qui fait tout l'intérêt du graphe, et elle repose sur deux
choses, pas une.

1. **La contrainte.** `fivPersonneCle` impose `p.cle` unique sur `:FivPersonne`,
   `fivGenreCle` fait de même sur `:FivGenre`. Neo4j refuse physiquement le
   doublon — ce n'est pas une convention que le code s'impose, c'est le moteur
   qui la fait respecter, y compris contre une requête écrite à la main.
2. **Le `MERGE` sur cette clé.** Toute écriture passe par
   `MERGE (p:FivPersonne {cle: $cle})` : la personne est créée la première
   fois, retrouvée ensuite. Ses propriétés se rafraîchissent
   (`SET p.nom = coalesce($nom, p.nom)` — un nom absent n'efface pas celui
   qu'on avait), et c'est la **relation** qui est nouvelle, jamais le nœud.

Vérifié contre un vrai serveur : Peter Dinklage projeté dans deux séries donne
**un** nœud portant deux `FIV_JOUE_DANS`, avec un rôle différent sur chacune —
le personnage est une propriété de la relation, pas de la personne, ce qui est
exactement pourquoi il peut différer d'une œuvre à l'autre.

La clé est `tmdb:<id>`, l'identifiant TMDB de la personne. Deux limites à
connaître, et elles ne sont pas dans le graphe :

- **Si TMDB a deux fiches pour un même acteur, on a deux nœuds.** Le graphe ne
  peut pas mieux faire que sa source. La réconciliation, le jour où elle sera
  utile, se fera en Postgres — une table `sourcing.personne` avec son pivot,
  comme `sourcing.oeuvre` l'a fait pour les œuvres — et le graphe suivra.
- **Un genre disparu ou un acteur retiré de toutes ses fiches laisse un nœud
  orphelin.** Sans conséquence (il ne remonte dans aucune traversée), et
  `graphe elaguer` le supprime.

---

## 6. Injecter et tenir à jour

Trois commandes, trois régimes. Aucune n'a besoin des deux autres pour être
correcte, mais elles se complètent.

| commande | ce qu'elle fait | quand |
|---|---|---|
| `graphe schema` | contraintes et index vectoriels | à l'installation, et après tout changement de barème |
| `graphe projeter` | l'univers entier, un état complet | première mise en service, changement de modèle |
| `graphe sync` | ce qui a bougé depuis le marqueur | chaque nuit, après la collecte |
| `graphe elaguer` | les nœuds devenus orphelins | de loin en loin |

### 6.1 Ce que la projection garantit

`graphe projeter` est **idempotent** : `MERGE` sur le pivot, et les relations que
la projection possède (les quatre du §4, pas les autres) sont effacées puis
réécrites œuvre par œuvre. Relancer deux fois donne exactement le même graphe —
mesuré — et un genre retiré d'une fiche recollectée **disparaît**, ce qu'un
`MERGE` seul ne saurait pas faire.

Une propriété absente part à `null`, jamais omise : `SET n += $props` retire une
propriété passée à null. C'est ce qui fait qu'une affiche disparue de TMDB
disparaît aussi du graphe, au lieu d'y vivre pour toujours.

On projette **un état, jamais un delta** — le même régime que `search reindex` et
`catalog refresh`. Un état est trivial à raisonner ; un delta ne l'est jamais.

**Limite connue, assumée.** Les cinq instructions d'un lot partent en cinq
requêtes, donc en cinq transactions : entre l'effacement des relations et leur
réécriture, une œuvre est momentanément nue. Sans conséquence tant que le graphe
se construit — personne ne le lit — et ça cessera de l'être le jour où il sert
des recommandations. Le remède est connu et local : les transactions explicites
de la Query API (`/db/<base>/query/v2/tx`).

### 6.2 Le rattrapage quotidien

`graphe sync` ne relit que ce qui a bougé depuis le marqueur, un nœud
`(:FivEtat {univers})` rangé **dans le graphe** : il meurt avec lui, et un graphe
reconstruit repart donc de son propre début — aucun état à tenir ailleurs.

Trois portes d'entrée déclenchent la reprojection d'une œuvre :

1. son pivot est neuf (`oeuvre.created_at`) — la collecte vient de la créer ;
2. sa fiche a été recollectée (`fetch_state.last_fetched_at`) — titre, genres ou
   distribution ont pu changer ;
3. **elle a été notée** (`notation.score.scored_at`).

La troisième est celle qu'un index de recherche n'a pas, et c'est elle qui rend
la commande utile ici : une campagne `training note` ne touche ni le brut ni
`fetch_state` — elle écrit dans `notation.score`. Sans cette porte, les
empreintes fraîches n'entreraient jamais dans le graphe.

L'heure du marqueur est prise **avant** la lecture des pivots : ce qui bouge
pendant l'envoi sera revu au passage suivant. Un recouvrement, jamais un trou.

Ce que `sync` ne fait pas : retirer une œuvre disparue du catalogue, et purger
les orphelins. Sans marqueur, elle refuse plutôt que de deviner.

### 6.3 La passe nocturne

`scripts/nightly.sh` enchaîne `graphe sync` après `search sync`, en `|| true` :
un graphe absent ou pas encore projeté ne doit pas faire échouer la collecte.
L'ordre compte — la synchronisation relit les métadonnées dans la projection de
vignettes, donc elle vient après `catalog refresh`.

---

## 7. Installation sur le serveur Debian

Tout est sous compose : rien à installer sur l'hôte, pas de JVM, pas de paquet
apt. C'est le seul avantage net du conteneur ici, et il est réel — l'archive de
Neo4j n'embarque pas de JVM, contrairement à celle d'Elasticsearch.

**1. Le mot de passe, dans `.env` à côté du compose.** Obligatoire : le compose
refuse de démarrer sans, et Neo4j refuse de démarrer avec `neo4j`.

```bash
cd /srv/fivorites            # là où le dépôt est cloné
openssl rand -hex 32         # copier le résultat
$EDITOR .env                 # NEO4J_PASSWORD=<le résultat>
```

Il est posé au **premier** démarrage et gravé dans le volume `neo4j-data` : le
changer dans `.env` ensuite ne change rien, il faut le changer dans la base
(`ALTER CURRENT USER SET PASSWORD FROM … TO …`). Éviter `/ + @ : # ?` — il part
tel quel dans une en-tête d'authentification.

**2. Démarrer le service, puis reconstruire l'image de l'admin** — elle porte le
code du graphe, qui est neuf :

```bash
sudo docker compose pull neo4j
sudo docker compose up -d neo4j
sudo docker compose build admin
sudo docker compose up -d admin
```

**3. Vérifier que Neo4j répond** avant d'essayer d'y écrire :

```bash
sudo docker compose exec neo4j wget -qO- http://localhost:7474/
```

Doit rendre un JSON portant `neo4j_version` et `neo4j_edition: community`. Si la
sonde répond mais que la suite échoue sur `Unable to connect to
http-driver.com:0`, c'est Bolt qui est coupé — voir le piège 1 du §8.

**4. Poser le schéma, puis injecter.** La première projection est la seule
longue : elle relit toutes les fiches collectées de l'univers.

```bash
sudo docker compose run --rm admin graphe schema
sudo docker compose run --rm admin graphe projeter --univers series
sudo docker compose run --rm admin graphe projeter --univers movies
sudo docker compose run --rm admin graphe etat
```

`graphe etat` doit montrer les deux index vectoriels en `ONLINE`, un compte
d'œuvres par univers, et un compte d'empreintes qui est **le seul chiffre qui
dit si la recommandation a de quoi travailler** : un graphe plein de nœuds et
vide de vecteurs répond à « qui joue dedans » et à rien d'autre.

**5. Brancher la passe nocturne.** `scripts/nightly.sh` appelle déjà
`graphe sync` — rien à faire si le cron de `doc/exploitation.md` §8 est en
place. Sinon :

```
30 10 * * *  /srv/fivorites/scripts/nightly.sh
```

**Une seule main à passer, de temps en temps** — l'élagage n'a aucune urgence :

```bash
sudo docker compose run --rm admin graphe elaguer
```

**Pour regarder le graphe à la main**, sur le serveur :

```bash
sudo docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (p:FivPersonne)-[:FIV_JOUE_DANS]->(o:FivOeuvre)
   RETURN p.nom, count(o) AS oeuvres ORDER BY oeuvres DESC LIMIT 10"
```

**Ou depuis un poste, avec le navigateur Neo4j.** Les ports sont publiés sur
`127.0.0.1` : un tunnel suffit, rien n'est ouvert sur le réseau.

```bash
ssh -L 7474:127.0.0.1:7474 -L 7687:127.0.0.1:7687 serveur
```

Puis `http://127.0.0.1:7474`. **Les deux ports sont nécessaires** : la page est
servie en 7474, mais c'est votre navigateur qui ouvre la session Bolt en 7687 —
n'en tunneliser qu'un donne une interface qui ne se connecte jamais.

Ouvrir vraiment le port à des adresses fixes est possible (`NEO4J_BIND` dans
`.env`) mais demande des règles `DOCKER-USER`, pas `ufw` — un `ufw deny` ne voit
pas un port publié par Docker. La recette complète, et ce qu'elle ne règle pas
(le trafic reste en clair), sont dans
[`serveur-debian11.md`](serveur-debian11.md) § « Exposer ES et Neo4j à des IP
fixes ».

**Si le graphe part de travers**, il est intégralement dérivé de Postgres — le
volume se jette sans rien perdre :

```bash
sudo docker compose down neo4j && sudo docker volume rm fivorites_neo4j-data
sudo docker compose up -d neo4j
sudo docker compose run --rm admin graphe schema
sudo docker compose run --rm admin graphe projeter
```

(Le nom exact du volume se lit avec `docker volume ls | grep neo4j` — il est
préfixé par le nom du projet compose.)

---

### 7.1 Cohabiter avec un autre Neo4j sur la même machine

Le cas s'est présenté à la mise en service : un Neo4j **déjà en service sur
l'hôte**, pour un autre usage, tenant 7474 et 7687 sur toutes les interfaces.
Le conteneur refuse alors de démarrer :

```
Error starting userland proxy: listen tcp4 127.0.0.1:7687: bind: address already in use
```

C'est un conflit de **ports publiés**, pas un conflit de bases. Une ligne le
règle :

```bash
printf 'NEO4J_HTTP_PORT=7475\nNEO4J_BOLT_PORT=7688\n' >> .env
```

Les deux instances sont alors étanches — conteneur séparé, volume séparé, JVM
séparée — et **rien du fonctionnement ne change** : `admin` joint la sienne par
le réseau interne du compose, où le port reste 7474 quoi qu'il arrive. Seul le
tunnel se décale :

```bash
ssh -L 7474:127.0.0.1:7475 -L 7687:127.0.0.1:7688 serveur
```

Le tunnel garde **7687 côté poste** : le navigateur Neo4j y ouvre sa session
Bolt en dur.

Ce que ça coûte : deux JVM et deux caches de pages sur la même machine, à côté
d'Elasticsearch et de Postgres. `NEO4J_HEAP` et `NEO4J_PAGECACHE` (1 Go chacun
par défaut) sont là pour ça — le graphe est petit en octets, et ce sont les
index vectoriels qui consomment, hors du tas.

Ce qu'on n'a **pas** fait, et pourquoi : réutiliser l'instance de l'hôte. Neo4j
Community n'autorise qu'une seule base par instance — pas de `CREATE DATABASE`
pour se ranger à côté — donc les deux graphes partageraient le même espace. Le
préfixe `Fiv` le rendrait techniquement sûr (§5), mais ce serait écrire dans
une base de production qui sert à autre chose, pour économiser une JVM.

---

### 7.2 Sur le poste de dev

Pas de conteneur — même règle que Postgres et Elasticsearch. Neo4j est
vendorisé dans `admin/vendor/`, version figée dans `.neo4j-version`, archive
vérifiée contre la somme publiée :

```bash
make -C admin bootstrap-neo4j    # affiche le mot de passe initial, une fois
make -C admin neo4j-start
```

**La seule dépendance système de tout le dépôt** : un Java 17 ou 21
(`brew install --cask temurin@21`, ou `apt install openjdk-21-jre-headless`).
`neo4j-start` le vérifie **en lançant** le Java qu'il a trouvé, pas seulement en
le localisant : sur macOS, `/usr/libexec/java_home -v 21` rend le JDK 18 de la
machine plutôt que d'échouer — mesuré ici. Sans cette vérification, Neo4j
recevrait une JVM inadaptée et tomberait sur un message qui ne parle pas de Java.

Puis les mêmes commandes que sur le serveur, sans le préfixe compose :
`.venv/bin/fiv-admin graphe schema`, `… projeter`, `… etat`.

---

## 8. Choix de version, et deux pièges mesurés

`neo4j:2026.07.1-community`, version calendaire plutôt que la LTS 5.26. **Une
seule raison résiste à l'essai** : le réglage `vector.quantization.type`, qui
n'existe que sur les calendaires et qui est ce qui permet de désactiver la
quantification (§3.2). L'autre raison envisagée — la clause `SEARCH` — ne tient
pas : elle appartient à Cypher 25 et le serveur interprète en Cypher 5 par
défaut, donc elle n'apporte rien tant qu'on n'écrit pas `CYPHER 25` en tête de
chaque requête.

Repli LTS possible si la cadence mensuelle devient un problème :
`5.26-community`, en remplaçant dans `graphe.schema_cypher` la ligne
`vector.quantization.type: 'none'` par `vector.quantization.enabled: false`.
Les requêtes, elles, n'ont pas à changer.

**Piège 1 : le port HTTP ne suffit pas.** Le client parle la Query API en HTTP
(7474), mais le serveur exécute la requête en repassant par **son propre pilote
Bolt** en interne. Avec `server.bolt.enabled=false`, la sonde HTTP répond, la
racine `/` répond, et la première vraie requête échoue sur
`Unable to connect to http-driver.com:0` — un message qui ne parle ni de Bolt
ni de configuration. Bolt doit être activé, même s'il n'est jamais joint de
l'extérieur. Mesuré ici ; la configuration du poste comme celle du compose
l'activent.

**Piège 2 : pas de retour à la ligne dans une instruction.** La Query API refuse
les sauts de ligne littéraux dans un `statement` — c'est du JSON. Le Cypher est
donc plié sur une ligne avant l'envoi, et **les commentaires `//` sont retirés
d'abord** : sans ça, le premier commentaire avalerait tout ce qui le suit, sans
la moindre erreur.

Le transport reste **HTTP et sans le pilote officiel** — même choix que pour
Elasticsearch, à qui `search.py` parle en httpx sans client dédié. Une
dépendance de moins dans l'image, et le protocole reste lisible dans les
journaux.

## 9. Ce qui n'est pas fait

- **Les membres.** `:FivMembre`, ses fives, ses swipes, et le vecteur de profil
  qui interrogera `fivEmpreinteCouleur`. C'est la suite immédiate — le graphe
  actuel décrit les œuvres, pas les goûts.
- **Les transactions explicites** de la projection (§5).
- **Le contrôle de dispersion** juge contre régression, que `empreinteSource`
  rend maintenant calculable mais que personne ne calcule encore.
- **La réconciliation des personnes** entre TMDB et Wikidata, qui demande un
  pivot `sourcing.personne` en Postgres (§5).
- **Les autres univers.** `books`, `bd`, `musics` : `LABEL_UNIVERS` les attend,
  et rien d'autre n'est à changer dans le modèle — c'est ce qu'on lui demandait.
