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

## 2. L'architecture en quatre décisions

**Un index par univers** (`catalog-series`, `catalog-movies`), pas un index
commun : les ids TMDB se chevauchent entre univers (1399 = *Game of Thrones*
ET un film), et l'id TMDB peut ainsi rester le `_id` du document. Chaque
univers se réindexe sans toucher l'autre, et `books` / `bd` / `musics`
s'ajouteront sans mapping fourre-tout.

**Des index horodatés derrière un alias** : la réindexation construit
`catalog-series-<horodatage>` à côté, bascule l'alias, supprime l'ancien —
zéro coupure, le même contrat que `refresh materialized view concurrently`.

**ES classe, Postgres hydrate.** Le document est minimal — titres, filtres
(affiche, synopsis, popularité), note bayésienne — et la recherche ne rend que
des ids ordonnés ; la page est hydratée par les requêtes SQL existantes
(`array_position` préserve l'ordre). Une seule source de vérité pour
l'affichage, pas de `nested`, pas de synchronisation de contenu.

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

Même logique que Postgres : **sur l'hôte, par apt** — pas un conteneur de
plus. Le conteneur admin le joint par la passerelle (`ES_URL`, défaut
`http://172.28.0.1:9200`, voir `.env.example`).

```bash
wget -qO- https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo gpg --dearmor -o /usr/share/keyrings/elasticsearch-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/elasticsearch-keyring.gpg] https://artifacts.elastic.co/packages/9.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-9.x.list
sudo apt update && sudo apt install elasticsearch
```

Dans `/etc/elasticsearch/elasticsearch.yml`, reprendre les réglages du poste
en ouvrant l'écoute à la passerelle Docker :

```yaml
cluster.name: fivorites
discovery.type: single-node
xpack.security.enabled: false     # port fermé au monde : pare-feu + écoute locale
xpack.ml.enabled: false
network.host: ["127.0.0.1", "172.28.0.1"]
```

et dans `/etc/elasticsearch/jvm.options.d/fivorites.options` : `-Xms2g` /
`-Xmx2g` (le catalogue complet, 1,5 M de documents par univers à terme).
`xpack.security.enabled: false` n'est acceptable que parce que le port
n'écoute que sur l'hôte et la passerelle interne — il ne doit jamais être
exposé ; sinon, activer la sécurité et passer l'URL avec identifiants dans
`ES_URL`.

Puis :

```bash
sudo systemctl enable --now elasticsearch
sudo docker compose run --rm admin search reindex
```

## 5. Au quotidien

* **Après une passe de collecte ou un `catalog refresh`** : `search reindex`.
  L'index ne se met jamais à jour au fil de l'eau — il se reconstruit en
  entier, comme la projection de vignettes. Jusque-là il est simplement en
  retard, exactement comme la projection avant son refresh. Le gros du temps
  part dans la relecture des payloads (les titres traduits ne vivent que dans
  le brut) : comptez long sur le catalogue complet, c'est un traitement par
  lots, pas une commande interactive.
* **`fiv-admin search status`** : santé, index en place, nombre de documents,
  taille. `docker compose run --rm admin search status` en production.
* **La recherche « marche mais bizarrement »** : vérifier `searchEngine` dans
  la réponse de `/api/catalog/cards`. `"sql"` = ES injoignable ou index
  absent, le journal de l'API dit lequel (`Elasticsearch indisponible…`).
* **Une œuvre collectée ne sort pas dans la recherche** : l'index date d'avant
  sa collecte — `search reindex`.

## 6. Ce qui n'est pas couvert (encore)

* Les ~44 700 œuvres Wikidata sans id TMDB (dont ~300 séries arabes sans aucun
  identifiant externe) ne sont pas indexées : les routes ne savent de toute
  façon pas les afficher. Le jour venu, `oeuvre_id` — déjà porté par chaque
  document — devient le `_id` et l'extraction gagne une source.
* Le synopsis n'est pas cherché : le champ `titres` suffit à la frappe, et
  l'index reste à ~30 Mo par univers là où les synopsis multilingues le
  multiplieraient par cent. À rediscuter si un besoin réel de recherche
  documentaire apparaît.
