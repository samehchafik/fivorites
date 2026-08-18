# Recherche plein texte — Elasticsearch

> Ce que ce document couvre : pourquoi la recherche passe par Elasticsearch,
> comment l'index est construit, comment l'installer (poste et serveur), et
> quoi faire quand elle se comporte mal. Le code de référence est
> `admin/src/fiv_admin/search.py`, dont l'en-tête reprend les décisions.

---

## 1. Ce que ça remplace, et ce que ça change

Avant : `ILIKE '%…%'` avec joker en tête — un balayage complet du catalogue à
chaque frappe (1,2 M de films sur le serveur), sur **deux champs seulement**
(`name`, `original_name`). Conséquence mesurable : « Le Trône de fer » était
introuvable, seuls « Game of Thrones » et les ids répondaient, alors que le
brut porte les titres dans ~45 langues.

Après : un `match` sur des préfixes précalculés, quelques millisecondes sur
1,5 M de documents, qui cherche dans **tous** les titres — nom courant, titre
original, titres alternatifs, traductions — avec pliage des accents (« trone »
trouve « Trône ») et classement par pertinence multipliée par la note
bayésienne de la grille.

ES est **facultatif** : s'il ne répond pas (absent, index pas construit,
panne), chaque route retombe sur son `ILIKE` historique, et un disjoncteur de
30 s évite de payer une tentative de connexion à chaque frappe. Rien ne casse,
la réponse de l'API porte `searchEngine: "es" | "sql"` pour dire d'où vient la
liste.

## 2. L'architecture en cinq décisions

**Un index par univers** (`catalog-series`, `catalog-movies`), pas un index
commun : les ids TMDB se chevauchent entre univers (1399 = *Game of Thrones*
ET un film), et l'id TMDB peut ainsi rester le `_id` du document. Chaque
univers se réindexe sans toucher l'autre, et `books` / `bd` / `musics`
s'ajouteront sans mapping fourre-tout.

**Des index horodatés derrière un alias** : la réindexation construit
`catalog-series-<horodatage>` à côté, bascule l'alias, supprime l'ancien —
zéro coupure, le même contrat que `refresh materialized view concurrently`.
Au quotidien l'index en place est **rattrapé par upsert** (`search sync`) :
chaque œuvre collectée ou nouvellement exportée y entre sans reconstruction,
grâce à un marqueur de reprise rangé dans l'index lui-même (`_meta`), qui
meurt et renaît avec lui.

**ES classe, Postgres hydrate.** Le document est minimal — titres, filtres
(affiche, synopsis, popularité), note bayésienne — et la recherche ne rend que
des ids ordonnés ; la page est hydratée par les requêtes SQL existantes
(`array_position` préserve l'ordre). Une seule source de vérité pour
l'affichage, pas de `nested`, pas de synchronisation de contenu.

**Et pas seulement la recherche : le parcours aussi.** Sans texte tapé, les
listes (grille et tableau, `status=all`) sont elles aussi servies par ES —
mêmes tris que le SQL (`missing: _last` = `nulls last`, départage sur l'id),
mêmes filtres, et le total arrive avec la page là où le SQL payait un
`count(*)` complet du catalogue à chaque affichage. Deux exceptions restent
au SQL, et c'est un choix : les filtres d'état (`fetch_state` bouge à chaque
passe) et le tri « fraîcheur » du tableau (sa jointure interne ne liste que
le déjà-regardé, une sémantique que l'index n'a pas).

**Jamais `popularity` dans le classement.** Le dictionnaire de données la
disqualifie (biais occidental, facteur 6 contre l'écriture arabe) ; le boost
de pertinence est la note bayésienne — la même formule que le tri de la
grille, figée dans le document à l'indexation.

Détail qui compte pour le tableau d'acquisition : son filtre d'état
(`collected`, `error`…) vit dans `fetch_state`, qui bouge à chaque passe de
collecte — il n'est **pas** indexé. ES rend les 2 000 meilleurs ids, le SQL
applique l'état dessus. Le total affiché est donc plafonné : une recherche
trop vague se précise, elle ne se pagine pas.

## 3. Poste de dev

```bash
make -C admin bootstrap-es   # télécharge dans admin/vendor/, vérifie le sha512
```

```bash
make -C admin es-start       # démarre en arrière-plan (idempotent)
```

```bash
admin/.venv/bin/fiv-admin search reindex
```

`es-stop` arrête le service. Les données vivent dans
`admin/vendor/elasticsearch/data` : non versionnées, reconstruites par
`search reindex`, jetables avec le reste de la toolchain. La configuration est
écrite par `make bootstrap-es` (mono-nœud, sans sécurité, fermé sur
127.0.0.1, tas de 1 Go) — la modifier dans le Makefile, pas dans `vendor/`.

Piège connu : sur un disque presque plein, les seuils d'allocation d'ES sont
en pourcentage (85/90/95 %) et le cluster reste `red` à vide. La configuration
écrite par le Makefile les passe en absolu (10/6/4 Go restants).

## 4. Serveur

**Un service du compose**, comme l'administration — rien à installer sur
l'hôte, rien à `systemctl`. C'est la différence avec Postgres, et elle tient
à une seule question : qu'est-ce qui se reconstruit ? Postgres porte la
collecte, qui ne se refabrique pas, donc il reste sur l'hôte. Un index de
recherche se refabrique intégralement depuis Postgres — le perdre ne coûte
qu'une réindexation, jamais une donnée. Il est donc conteneurisé, avec son
volume nommé `es-data`.

Le service n'a **aucun port publié** : seul le conteneur `admin` le joint,
par le réseau interne du compose (`ES_URL` vaut `http://elasticsearch:9200`,
et n'a pas à être renseigné dans le `.env`). C'est ce qui rend
`xpack.security.enabled: false` acceptable — la liaison ne sort jamais de la
machine. Corollaire à ne pas oublier : **ne jamais ajouter de `ports:` sans
activer la sécurité en même temps.**

### Le seul prérequis hôte

Elasticsearch 9 exige `vm.max_map_count = 1048576`, un réglage du noyau que
Docker ne peut pas poser depuis un conteneur (il n'est pas « namespacé »).
C'est la seule commande de cette page qui ne soit pas du `docker compose` —
une fois pour la vie de la machine :

```bash
echo 'vm.max_map_count=1048576' | sudo tee /etc/sysctl.d/99-elasticsearch.conf && sudo sysctl --system
```

Sans lui, le conteneur démarre puis s'arrête, avec dans ses journaux
`max virtual memory areas vm.max_map_count [65530] is too low`. C'est le
premier endroit à regarder si `search status` répond « injoignable » après
un déploiement.

### La mise en service

```bash
git pull && sudo docker compose build admin
```

```bash
sudo docker compose up -d elasticsearch
```

```bash
sudo docker compose run --rm admin search reindex
```

```bash
sudo docker compose up -d admin
```

La réindexation avant le redémarrage de l'admin, pour qu'il ne serve pas des
listes en repli SQL pendant que l'index se construit. `up -d admin` démarre
de toute façon `elasticsearch` avec lui (`depends_on`), mais sans attendre sa
santé : l'administration est conçue pour tourner sans recherche, on ne lui
attache pas son sort — un ES en panne ne doit jamais empêcher un
`db migrate`.

### Régler la mémoire

Deux variables dans le `.env`, si les valeurs par défaut ne conviennent pas
(2 Go de tas, conteneur plafonné à 3 Go) :

```bash
ES_JAVA_OPTS=-Xms2g -Xmx2g
ES_MEM_LIMIT=3g
```

**Le tas se dimensionne au volume indexé, pas à la RAM de la machine**, et
c'est contre-intuitif : sur un serveur à 125 Go, la tentation est d'en donner
beaucoup. Ce serait contre-productif. L'index mesuré fait 159 octets par
document — 35 Mo pour 228 000 séries, soit ~230 Mo pour le catalogue complet
(1,46 M d'œuvres). Deux gigaoctets de tas sont déjà confortables ; au-delà,
on n'accélère rien et on allonge les pauses du ramasse-miettes. Ce qui rend
la recherche rapide sur un gros index, c'est le cache de fichiers du système,
donc la mémoire laissée LIBRE — pas celle donnée à la JVM.

Deux garde-fous pour mémoire : ne jamais dépasser ~31 Go de tas (au-delà, la
JVM perd la compression des pointeurs et l'on dispose de *moins* de mémoire
utile), et garder `mem_limit` au-dessus du tas, la JVM ayant besoin de place
hors tas.

### Regarder ce qui se passe

Sans port publié, on passe par le conteneur :

```bash
sudo docker compose exec elasticsearch curl -s localhost:9200/_cat/indices
```

ou, plus simplement, par la commande qui met déjà en forme :

```bash
sudo docker compose run --rm admin search status
```

## 5. Au quotidien

* **Les imports entrent seuls dans ES.** La passe nocturne enchaîne
  `catalog refresh` puis `search sync`, et le bouton de rafraîchissement de
  l'admin fait de même : tout ce qu'une passe de collecte ou un export a
  touché est réextrait et upserté dans l'index en place — quelques secondes
  pour un lendemain ordinaire. L'ordre compte : la synchronisation relit les
  métadonnées de vignette dans la projection, donc **toujours après le
  refresh**.
* **`search reindex` reste la voie lourde**, pour trois cas seulement : la
  première mise en service, un changement de mapping, et la purge des œuvres
  disparues du catalogue (la synchronisation ajoute et met à jour, elle ne
  retire pas). Le gros du temps part dans la relecture des payloads : comptez
  long sur le catalogue complet, c'est un traitement par lots.
* **`fiv-admin search status`** : santé, index en place, nombre de documents,
  taille. `docker compose run --rm admin search status` en production.
* **Les listes « marchent mais bizarrement »** : vérifier `searchEngine` dans
  la réponse de `/api/catalog/cards` ou `/api/acquisition/items`. `"sql"` =
  ES injoignable ou index absent, le journal de l'API dit lequel
  (`Elasticsearch indisponible…`).
* **Une œuvre importée ne sort pas** : `search sync` n'a pas encore tourné
  depuis son import — le relancer, ou attendre la passe nocturne. Si la
  commande répond « index sans marqueur », l'index date d'avant les
  marqueurs : `search reindex` une fois, et la synchronisation prend le
  relais.

## 6. Ce qui n'est pas couvert (encore)

* Les ~44 700 œuvres Wikidata sans id TMDB (dont ~300 séries arabes sans aucun
  identifiant externe) ne sont pas indexées : les routes ne savent de toute
  façon pas les afficher. Le jour venu, `oeuvre_id` — déjà porté par chaque
  document — devient le `_id` et l'extraction gagne une source.
* Le synopsis n'est pas cherché : le champ `titres` suffit à la frappe, et
  l'index reste à ~30 Mo par univers là où les synopsis multilingues le
  multiplieraient par cent. À rediscuter si un besoin réel de recherche
  documentaire apparaît.
