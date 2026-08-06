# Avancement — acquisition des séries

> Journal de ce qui a été construit, décidé et mesuré. Conçu pour être
> **auto-suffisant** : ouvrir un thread avec ce seul fichier doit suffire à
> reprendre le travail.
>
> Compléments : [`architecture-sourcing.md`](architecture-sourcing.md) pour
> l'architecture cible, [`v2-acquisition-series.md`](v2-acquisition-series.md) pour le
> plan, [`v2-notation-axes.md`](v2-notation-axes.md) pour la couche 2,
> [`serveur-debian11.md`](serveur-debian11.md) pour l'installation,
> [`exploitation.md`](exploitation.md) pour le quotidien,
> [`sourcing/README.md`](../sourcing/README.md) pour l'usage courant.
> Les deux études : [couverture du marché arabe](etude-couverture-marche-arabe.md)
> et [sources complémentaires](etude-sources-complementaires.md).
>
> Dernière mise à jour : 2026-08-06.

---

## 1. Où on en est

Les lots 1 (socle), 2 (catalogue et collecte de masse) et 3 (enrichissement
externe) sont livrés. Le pipeline sait inventorier tout TMDB, collecter chaque
série, et l'enrichir par Wikidata, Wikipédia et TVmaze.

**Le jeton TMDB est réparé et la collecte tourne** (2026-08-06). Mesuré sur le
serveur : 2,06 séries/s, **zéro échec**, le limiteur saturé à 20 req/s — c'est
donc le plafond configuré qui borne, pas le réseau ni la base.

| | État |
|---|---|
| Poste de dev | opérationnel, catalogue de 228 454 séries chargé |
| Serveur Debian 11 | opérationnel |
| Collecte TMDB | **en cours** — ~148 600 séries collectées, ~79 800 restantes (~11 h) |
| Enrichissement | opérationnel, et indépendant du jeton |
| Tests `sourcing` | 138 — 69 unitaires, 69 de bout en bout sur Postgres |
| Tests `admin` | 85 |
| Code `sourcing` | ~3 100 lignes de source, ~1 900 de tests |

---

## 2. Ce qui existe

### 2.1 Les commandes

```bash
fiv-sourcing doctor                    # interpréteur, base, migrations, schéma, jeton TMDB
fiv-sourcing db migrate                # applique les migrations manquantes

fiv-sourcing tmdb export               # charge la liste de toutes les séries (public, hors quota)
fiv-sourcing tmdb catalog              # volumétrie et déciles de popularité
fiv-sourcing tmdb fetch --id 1399      # collecte une série
fiv-sourcing tmdb backfill             # collecte tout le catalogue, reprenable
fiv-sourcing tmdb dates                # recopie les dates du brut vers l'inventaire
fiv-sourcing tmdb changes --days 1     # marque ce que TMDB signale comme modifié
fiv-sourcing tmdb stats                # ce qui est en base + projection de volume

fiv-sourcing enrich --id 1399          # sources tierces sur une série
fiv-sourcing enrich                    # toutes celles sans complément, reprenable

fiv-sourcing crawl wikidata --langue ar  # les séries hors TMDB (noyau dur), reprenable
```

`backfill` et `enrich` acceptent tous deux `--limit`, `--concurrency`,
`--order`, `--refresh-after` et `--dry-run`, et s'interrompent proprement sur un
seul Ctrl-C ou un `docker stop`. Les deux **refusent de démarrer si une migration
est en attente** : une passe dure des heures, elle doit échouer à la première
seconde et nommer ce qui manque.

`--order recent` trie par année de diffusion décroissante puis popularité — ce
que `popularity` seul ne fait pas. Il demande que `tmdb dates` ait tourné.

Le débit de `enrich` est **par hôte** : `ENRICH_RATE_LIMIT` (5) pour Wikimedia,
`TVMAZE_RATE_LIMIT` (2) pour TVmaze, dont la limite est documentée.

### 2.2 Le schéma

Une base — `fivorites_v2` — et un schéma par domaine.

| Table | Rôle |
|---|---|
| `sourcing.raw_source` | le brut, append-only, une ligne par réponse HTTP |
| `sourcing.fetch_state` | fraîcheur et état par objet ; remplace les 3 fichiers JSON de la V1 |
| `sourcing.tmdb_catalog` | inventaire du catalogue, issu de l'export quotidien ; `first_air_date` y est dérivée du brut |
| `sourcing.oeuvre` | le **pivot d'identité** — id propre, identifiants externes nullables et uniques ; accueille les œuvres hors TMDB |
| `sourcing.riche_source` | l'enrichissement, attaché au pivot (`oeuvre_id`) ; `id_tmdb` et `raw_source_id` nullables |
| `public.schema_migrations` | historique des migrations, valable pour la base entière |

`riche_source` porte `raw_source_id` (la fiche référencée), `id_tmdb`,
`content` (le texte à noter), `media`, `url`, **`facts`** — le seul lieu de vie
des faits tiers : pays, langue, lieux P915/P840, dates et diffuseur TVmaze —,
deux compteurs calculés (`content_chars`, `media_count`) et **`resolved_by`**,
le chemin qui a raccordé la série (`p4983`, `p345`, `p8600`, `imdb`, `title`,
`sitelink`). Sans cette colonne, le taux de résolution par chemin serait une
étude à refaire ; avec elle, c'est un `group by`.

La couche 2 (axes) aura son schéma au lot suivant — ⚠️ son nom n'est pas tranché,
voir §7.

### 2.3 Les invariants

**Une réponse HTTP = une ligne de `raw_source`.** C'est ce qui donne à chaque
saison sa propre fraîcheur, son propre statut et sa propre empreinte. Le
regroupement des saisons sous une série appartient à la dérivation. À la
question « pourquoi pas une colonne `saisons[]` » : parce qu'un tableau
imposerait de réécrire toute la série pour rafraîchir une saison, invaliderait
l'empreinte du bloc entier au moindre changement, et rendrait les échecs
tout-ou-rien.

**Le brut porte TMDB et Wikidata/Wikimedia — jamais TVmaze** (R1 de
[`architecture-sourcing.md`](architecture-sourcing.md), qui a remplacé la
décision « exclusivement TMDB » du même jour). La dérivation est ainsi
rejouable hors ligne ; TVmaze, enrichissement pur, se rejoue en réinterrogeant.
`riche_source` n'est jamais une copie du brut (R2) : ses `facts` sont au format
canonique produit par `normalize.py` (R5) — la seule frontière avec les formats
propriétaires. Piège attrapé en vrai : Blazegraph ne garantit pas l'ordre des
`GROUP_CONCAT`, et sans canonicalisation chaque rejeu écrivait une ligne de
brut pour un contenu identique.

**Rejouer une collecte inchangée n'écrit rien.** Déduplication par SHA-256 du
payload canonicalisé. `riche_source`, elle, est **remplacée** à chaque passe :
les deux tables n'ont pas le même contrat, et un test le fige.

**Un 404 se conserve, un 401 non.** Le premier est un fait sur la source — « cet
id a disparu de TMDB ». Le second ne dit rien de l'œuvre, seulement de notre
configuration ; le stocker polluerait le brut d'autant de lignes que d'ids
tentés le jour où un jeton expire.

**Ce qui décide de la reprise, c'est `fetch_state`.** Pour l'enrichissement, le
critère n'est *pas* la présence d'une ligne dans `riche_source` : 64 % des
séries n'ont pas d'item Wikidata et n'en produiront donc jamais. S'y fier ferait
retenter tout le fond de catalogue à chaque passe. La question posée est « a-t-on
déjà regardé ? ».

---

## 3. Décisions

| Sujet | Décision | Pourquoi |
|---|---|---|
| **Catalogue V1** | table rase | TMDB est re-collectable ; seuls les fives utilisateurs sont irremplaçables |
| **Filtrage à l'acquisition** | **aucun** | voir §5.2 — `popularity` écarterait les catalogues arabe et turc |
| **Tri du backfill** | `id` par défaut | trier par popularité serait un jugement implicite |
| **Langues des saisons** | fr, en, es, ar, tr | un appel par langue : seul moyen d'obtenir les synopsis d'épisode traduits |
| **Sources tierces** | Wikidata + TVmaze, **IMDb écartée** | voir §5.3 et §5.4 |
| **Entrée dans Wikidata** | `P4983` (id TMDB), `P345` en second | ne suppose aucune collecte préalable |
| **Appariement TVmaze** | le titre cherche, l'`imdb_id` décide | voir §5.4 — aucun seuil de score |
| **Python** | 3.12 vendorisé dans `sourcing/vendor` | aucune dépendance à un interpréteur système |
| **Postgres** | toujours sur l'hôte, jamais en conteneur | dev comme serveur |
| **Docker** | serveur uniquement, pour l'application | le poste de dev n'en utilise pas |

**Le pivot `oeuvre`** (2026-08-06) répond à une mesure : la moitié des items
« série » de Wikidata n'a pas d'identifiant TMDB, 300 des 480 séries de langue
arabe n'ont *aucun* identifiant externe, et TVmaze ne porte jamais d'id TMDB.
Aucun « id média universel » n'existe dehors ; le nôtre est `oeuvre.id`, avec
les identifiants externes nullables et uniques par univers. Une série hors TMDB
entre par là (`id_tmdb` et `raw_source_id` nuls dans `riche_source`), et la
réconciliation tardive est prévue : les index uniques empêchent le doublon, une
collision est journalisée comme « réconciliation à faire », jamais absorbée en
silence. Le point d'entrée de saisie (par QID ou par titre) reste à écrire.

**Sur IMDb**, la décision mérite d'être écrite en clair parce qu'elle reviendra :
ni datasets, ni scraping. La licence exclut l'usage commercial et les conditions
interdisent l'extraction, que l'on republie ou non. Et le renoncement est faible
— `alternative_titles`, `external_ids` et les votes sont déjà dans le
`SERIES_APPEND` de TMDB, et la note ne nourrit **aucun** des 6 axes, qui
décrivent un contenu et non une qualité. En revanche **l'`imdb_id` reste** :
c'est un identifiant, pas une donnée d'IMDb, et c'est le signal décisif de
l'appariement TVmaze.

---

## 4. Coût

### 4.1 Collecte TMDB

Par série : 1 appel pour la fiche (avec `translations`, donc toutes les langues
d'un coup) + 1 appel **par saison et par langue**. Une série de 8 saisons =
41 requêtes avec les cinq langues.

**Mesuré sur le serveur** : 2,06 séries/s à `TMDB_RATE_LIMIT=20`, soit environ
10 requêtes par série en moyenne — la plupart des séries ont peu de saisons. Sur
228 454 séries, cela fait ~2,2 millions de requêtes et **une trentaine
d'heures**. L'extrapolation initiale était juste.

Le limiteur est saturé : 2,06 × 10 ≈ 20 req/s. Ce n'est donc ni le réseau ni la
base qui bornent, mais le plafond configuré — voir la question ouverte sur le
débit réellement toléré.

⚠️ **À vérifier avant d'engager la passe complète** : l'endpoint `translations`
d'une saison suffirait-il à remplacer les cinq appels ? Ma compréhension est
qu'il ne couvre que le nom et le synopsis *de la saison*, pas l'`overview` de
chaque épisode — mais si je me trompe, le coût des saisons est divisé par cinq.
Une seule requête suffit à trancher.

### 4.2 Enrichissement — mesuré

Sur 60 séries tirées au hasard du catalogue réel :

| | |
|---|---|
| Raccordées (item Wikidata) | 22 / 60 — **36 %** |
| Requêtes | 70, soit **1,17 par série** |
| Débit observé | 1,7 série/s à `ENRICH_RATE_LIMIT=2` |
| **Projection sur 228 454 séries** | **~37 heures**, ~267 000 requêtes |

Ce chiffre ne tient que grâce au **regroupement des résolutions** : une requête
SPARQL pour cent séries, donc 2 300 requêtes de résolution au lieu de 228 000.
Adresser 228 000 requêtes au service SPARQL de Wikidata — gratuit et partagé —
ne se fait pas, indépendamment du temps que ça prendrait.

---

## 5. Ce qui a été mesuré

### 5.1 Volumétrie

**228 454 séries**, export du 2026-08-05, téléchargé et chargé en 4 secondes.
Le fichier est public : aucune clé, aucun quota consommé.

| Popularité ≥ | Séries | Part |
|---|---|---|
| 1 | 110 437 | 48 % |
| 5 | 14 593 | 6,4 % |
| 10 | 5 059 | 2,2 % |
| 20 | 1 733 | 0,8 % |

La falaise est brutale : le premier décile couvre 406 → 3,71, les neuf autres se
partagent 3,71 → 0.

### 5.2 ⭐ Pourquoi `popularity` ne peut pas servir de filtre

C'est la mesure la plus structurante du projet.

`popularity` est une métrique d'usage **du site TMDB**, dont la base
d'utilisateurs est très majoritairement occidentale.

| Écriture | Séries | Popularité médiane | % ≥ 5 |
|---|---|---|---|
| latin / autre | 166 753 | 0,89 | **6,3 %** |
| CJK | 49 839 | 1,11 | **7,4 %** |
| arabe | 5 560 | 1,10 | **1,0 %** |
| cyrillique | 4 762 | 1,33 | 3,6 % |
| indices turcs | 1 540 | 1,83 | 13,3 % |

**Un seuil à 5 retiendrait 54 des 5 560 séries en écriture arabe** — une
sous-représentation d'un facteur six. Et les médianes sont comparables : ces
séries ne sont pas « moins populaires », leur distribution n'a simplement pas de
tête longue sur TMDB. *Al-Ikhtiyar* (الاختيار), l'une des plus grosses
productions égyptiennes récentes, est à 3,44 — écartée.

⚠️ **Réserve** : la détection du turc par `[ğışĞİŞ]` rate *Kara Sevda*, *Ezel*.
Les 1 540 sont un plancher. La détection de l'arabe, elle, est fiable.

**Conclusion** : aucun filtre à l'acquisition.

### 5.3 Ce qu'apportent les sources tierces

Étude du 2026-08-06 sur 230 séries — 15 par décile, plus les 40 plus populaires
en écriture arabe et les 40 en écriture turque.

| Indicateur | Part |
|---|---|
| Item Wikidata (`P4983`) | 38,7 % |
| …dont identifiant IMDb | 35,7 % |
| **Série trouvée sur TVmaze** | **40,0 %** |
| Note IMDb disponible | 34,3 % (96,3 % des séries raccordées) |

**TVmaze trouve plus que Wikidata**, et par un autre chemin : la recherche par
titre y récupère 19 séries que Wikidata ignore entièrement (12,7 % de la strate
par décile).

**Mais c'est un raccordeur, pas une source de texte.** Sur les séries trouvées :
99,2 % des 6 482 épisodes datés, 100 % avec diffuseur et statut, 84,8 % avec
calendrier — et **35,9 % seulement ont des résumés d'épisode**.

Deux résultats de périmètre :

- **Le fond de catalogue est invisible aux trois sources.** Au dixième décile :
  0 % d'item Wikidata, 6,7 % de série TVmaze. Au-delà du troisième décile,
  l'enrichissement externe cesse d'être une stratégie.
- **Le corpus arabe reste bloqué** : 40 % de raccordement, 7,5 % de résumés
  d'épisode. Aucune des trois sources ne le débloque — il faudra une source
  dédiée (elCinema, Shahid, recherche par titre dans Wikipédia arabe) ou rien.

### 5.4 Le protocole d'appariement TVmaze

Mesuré contre une vérité terrain gratuite : les 64 séries qui portent à la fois
`P4983` et `P8600` dans Wikidata sont des paires TMDB↔TVmaze déjà vérifiées par
des humains.

| Signal | Résultat |
|---|---|
| Top 1 correct, titre seul | 58 / 64 (90,6 %) |
| …que le seuil « score ≥ 0,9 » accepte | 35 / 58 — il **rejette 23 bons** |
| Faux positif passant le seuil | 1 (*Teen Wolf* → l'homonyme) |
| `externals.imdb` confirme le bon | **50 / 51** |
| …oppose son veto au faux positif | **1 / 1** |

D'où la règle retenue : **le titre sert à chercher, l'`imdb_id` à décider**.
Aucun seuil de score. Sans identifiant des deux côtés, on n'écrit rien — une
ligne fausse coûte plus qu'une ligne absente, parce qu'elle ne se signale pas.

### 5.5 `P4983` ne remplace pas `P345`, il s'y ajoute

Contre-mesure utile, parce que l'intuition inverse est tentante :

| Séries | portent un `P4983` **sans** `P345` |
|---|---|
| langue arabe | **6** |
| langue turque | **8** |
| toutes langues | 5 915 |

Le gain global est réel mais presque entièrement occidental — là où la chaîne
par IMDb marche déjà à 98 %. Là où elle casse, l'entrée par identifiant TMDB
rapporte six séries. Les deux se cumulent, elles ne se remplacent pas.

**Le goulot n'est pas l'identifiant, c'est l'item** : Wikidata ne connaît que de
l'ordre de 663 séries de langue arabe (plancher — `P364` est souvent absente)
contre 4 898 `original_language=ar` chez TMDB. Aucune jointure ne récupère ce
qui n'est pas écrit.

### 5.6 Ce qu'une série bien dotée rapporte

*Game of Thrones*, 8 requêtes d'enrichissement :

| Source | Caractères |
|---|---|
| Wikipédia es | 77 510 |
| Wikipédia en | 71 333 |
| Wikipédia fr | 60 538 |
| Wikipédia ar | 30 609 |
| Wikipédia tr | 18 369 |
| TVmaze (résumés d'épisode) | 11 740 |
| **Total** | **~258 000** |

Contre 400 caractères pour l'overview TMDB. C'est cet ordre de grandeur qui
tranchera le périmètre notable au lot 5.

---

## 6. Défauts trouvés et corrigés

Utile pour ne pas les réintroduire.

### Hérités de la V1

- **`append_to_response` demandait `releases` et `lists`** — endpoints *films*,
  demandés sur des séries depuis 2017. Deux sous-requêtes pour rien.
- **`external_ids` absent** — sans lui, aucun raccordement possible.
- **`id_tmdb` non stocké** — la ligne était commentée dans le ColumnSet V1.
  À corriger au lot 4 : unique et indexée.

### Introduits et corrigés pendant ce chantier

- **uv détruisait la venv vendorisée.** `UV_PYTHON_INSTALL_DIR` n'est pas une
  clé de `uv.toml` — uv ne la lit que dans l'environnement. Trois verrous : le
  Makefile exporte la variable, aucune cible n'appelle `uv run`, `make guard`
  échoue avant tout.
- **`migrate` réussissait sur un répertoire absent.** Erreur bruyante désormais.
- **L'image se construisait avec un module manquant.** Test de fumée au
  `Dockerfile` : tous les modules sont importés au build.
- **Les tests ont vidé la base de travail** — 228 000 séries perdues. Base
  `_test` séparée depuis.
- **`doctor` ne validait pas le jeton TMDB.** Il fait un appel réel maintenant.
- **Mot de passe en base64 dans une URL de connexion** — `/` et `+` y sont
  réservés. Le runbook impose `openssl rand -hex`.
- ⭐ **Une migration n'arrive pas par `git pull`.** Les `Dockerfile` font
  `COPY migrations ./migrations` et `MIGRATIONS_DIR` pointe dedans ; aucun volume
  ne les monte. Sans `docker compose build`, `db migrate` lit les migrations
  d'avant le pull et répond « base déjà à jour » — le message le plus trompeur
  possible, puisqu'il est vrai du point de vue du conteneur. **C'est arrivé en
  vrai** avec `004_series_source.sql`.
- **`WEB_DIST=/srv/www/dist` périmé** dans l'image admin, reliquat d'avant la
  séparation `front/` → `www/`. Le compose surchargeait la variable, donc la
  production marchait et l'image lancée seule non.
- **Le `worker` de l'enrichissement capturait la tranche par fermeture.** Correct
  tant qu'on attend avant l'itération suivante, faux dès qu'on enlève l'attente.
  Extrait en fonction à paramètres.
- **Le compteur « enrichies » annonçait 16 pour 22 lignes en base** — la ligne
  `wikidata` s'écrit pendant la résolution du lot, hors du rapport de détail. Un
  test compare désormais le compteur à ce qu'il y a réellement en base.
- **Une requête gaspillée par série** : la recherche TVmaze par titre partait
  même sans `imdb_id`, donc sans aucune chance d'aboutir — sur 64 % du catalogue.

### Vérifiés plutôt que supposés

- **Connexion psycopg partagée entre tâches concurrentes** : `cursor.execute`
  prend le verrou, les écritures se sérialisent. Une seule connexion suffit.
- **Ordre réseau Docker / Postgres** : `172.28.0.1` n'existe qu'après création du
  réseau Docker. Le runbook crée le réseau avant `listen_addresses`.
- **Pare-feu** : Docker programme FORWARD et NAT, pas INPUT. Signature d'un
  blocage : `ConnectionTimeout`, pas `connection refused`.

---

## 7. Questions ouvertes

Par ordre de ce qui bloque.

1. ✅ ~~Le jeton TMDB est refusé~~ — **réparé le 2026-08-06**, la collecte tourne
   sans un seul échec. Pour mémoire, si le cas revient : un token v4 est un JWT
   qui commence par `eyJ`, ~200 caractères, deux points ; une clé v3
   (32 hexadécimaux) va dans `TMDB_API_KEY`, pas `TMDB_BEARER`.
2. 🔴 **Licence TMDB.** Libre en usage non commercial avec attribution ; un usage
   commercial demande leur accord. Le seul point qui pourrait invalider tout ce
   qui est construit. À lever **avant** la passe complète.
3. 🟠 **Clé d'API en clair et versionnée** dans
   [`tools/etude_couverture_ar.py`](../tools/etude_couverture_ar.py) — une clé
   TMDB V1. Elle est déjà dans l'historique git : la déplacer ne suffit pas, il
   faut la **révoquer**.
4. 🟠 **Nom du schéma de la couche 2.** `v2-notation-axes.md` dit `notation` avec
   `notation.score` ; le diagramme de `v2-acquisition-series.md` dit `scores`
   avec `series_scores`. Deux noms pour la même chose, et ce nom finira dans une
   migration.
5. 🟠 **Volume disque.** Non mesuré. `tmdb backfill --limit 200` puis
   `tmdb stats` donne la projection, à comparer à `df -h`.
6. 🟠 **Débit toléré par TMDB.** La limite dure a été supprimée en 2019 ; ce qui
   subsiste n'est pas documenté. Défaut prudent : 20 req/s, et le limiteur y est
   saturé — c'est lui qui borne la passe, pas le réseau. Zéro échec observé sur
   les premières centaines de séries, donc il y a probablement de la marge : le
   bilan des 429 en fin de passe le dira. **Le limiteur est par processus** —
   lancer deux passes double le débit réel vers TMDB, ce qui est arrivé une fois
   (trois `backfill` simultanés) et ne se voit nulle part.
7. 🟠 **Écart de version Postgres** : 16 en dev, **13** sur le serveur — le dépôt
   PGDG du runbook n'a pas été utilisé. Rien n'exige aujourd'hui plus que la 13,
   mais l'écart est à résorber avant que la base contienne des données coûteuses.
8. ⚠️ **`translations` sur les saisons** — cf. §4.1, facteur cinq sur le coût.
9. ⚠️ **De l'instabilité inter-tests, vue deux fois.** Une passe complète a
   échoué une fois sur 7 tests (autour de `test_enrich_all`), puis cinq passes
   vertes d'affilée sans reproduction ; même signature qu'un échec isolé
   antérieur. Les suspects comptent des lignes exactes sur la base partagée. Si
   ça revient, isoler avec `pytest -p no:cacheprovider` et regarder l'ordre
   d'exécution.
10. ⚠️ **Marchés visés.** Un catalogue équilibré fr / en / es / ar / tr n'a pas la
    même forme qu'un catalogue francophone avec des ouvertures. N'affecte pas
    l'acquisition (on prend tout), mais déterminera ce qu'est une couverture
    suffisante au lot 5.

---

## 8. Suite

| Lot | Contenu |
|---|---|
| 4 | Dérivation de la couche 1 : `catalog.series`, `id_tmdb` unique et indexé, `series_locations`, `series_people` |
| 5 | **Rapport de couverture** — le vrai livrable : matière textuelle disponible par décile |
| 6 | Priorités de rafraîchissement (`/tv/changes` est déjà là) |

Le lot 5 est celui qui tranche le périmètre et le budget de notation. Il fournit
aussi le **constructeur de dossier de notation** : la fonction
`series_id → texte prêt à noter`, interface exacte entre acquisition et couche 2.
`riche_source.content_chars` a été conçue pour qu'il se calcule sans relire un
seul article.

**Le premier livrable concret qui reste** : lancer `enrich` sur tout le catalogue
(~37 h) et lire le taux de raccrochage réel dans `riche_source.resolved_by`.
Ça ne demande pas le jeton TMDB.

---

## 9. État du dépôt

`main` et `origin/main` sont à `1182025`. La branche
`claude/documentation-review-5ceea7` porte **un commit de plus**, `c813d45`
(enrichissement de tout le catalogue), ni mergé ni poussé.

| Hash | Contenu |
|---|---|
| `c813d45` | ⚠️ *sur la branche seulement* — enrichir tout le catalogue, cent séries par requête |
| `81b45dc` | les sources tierces, sans repasser par TMDB (`enrich --id`) |
| `72aa82a` | une migration n'arrive pas par `git pull`, mais par `docker build` |
| `7b04797` | IMDb sort du plan |
| `0e113b9` | l'appariement TVmaze : titre pour chercher, `imdb_id` pour décider |
| `5511713` | ce qu'apportent Wikidata, TVmaze et IMDb, mesuré |
| `cf07e04` | la table d'enrichissement (devenue `riche_source` en 006) |
| `e0ec248` | remettre la documentation d'accord avec le code |
| `46aa882` | mesure du plafond de débit TMDB |
| `c58a307` | catalogue complet et collecte de masse |
| `088f30b` | collecte des saisons en cinq langues |
| `b6027f5` et avant | socle, schéma, déploiement |

### Déployer sur le serveur

L'ordre compte, et le `build` n'est pas optionnel quand une migration est
arrivée :

```bash
git pull
sudo docker compose build sourcing
sudo docker compose run --rm sourcing db migrate
sudo docker compose run --rm sourcing doctor        # doit dire « 4 table(s) »
```

Contrôle si un doute subsiste sur ce que l'image embarque :

```bash
sudo docker compose run --rm --entrypoint ls sourcing /app/migrations
```
