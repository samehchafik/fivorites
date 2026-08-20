# Migrer la V1 dans la V2 — utilisateurs, films, séries

**Oui, c'est possible**, et la raison tient en une ligne : la V1 a rangé un
identifiant TMDB dans `source_acquisition` de ses catalogues, et la V2 est bâtie
sur un pivot d'identité qui sait exactement quoi en faire. L'appariement n'a donc
pas à passer par les titres — sauf pour une minorité, chiffrée plus bas.

Ce document décrit le chemin. Il ne migre rien : il dit ce qui est mesuré, ce qui
manque, ce que l'export doit contenir, et dans quel ordre les lots s'enchaînent.

Les mesures ci-dessous ont été prises le **2026-08-20**, côté V1 sur la base
`fivorites` locale, côté V2 **sur la production** (`51.195.4.32`). La copie
locale de `fivorites_v2` est en retard de plusieurs lots — elle ne connaît ni les
films ni les œuvres collectées, et ne doit servir à mesurer quoi que ce soit.

La base V1 locale est un instantané arrêté au **2021-02-23** ; c'est le dernier
état connu de la V1, et c'est lui qu'on migre.

---

## 1. Ce qu'il y a des deux côtés

### Côté V1 — un schéma par univers, les gens dans `public`

| Table | Lignes | Ce que c'est |
|---|---:|---|
| `public.personnes` | 69 355 | **la personne** : pseudo, bio, avatar, réseaux, compteurs |
| `public.users_auth` | 32 349 | **le compte** : email, mot de passe, dates — même `id` que `personnes` |
| `public.users` | 0 | vestige, vide, à ignorer |
| `fives.catalog` | 76 870 | **un top-5** = (utilisateur, univers, période) ; les cinq œuvres sont dans `tops json[]` |
| `fives.catalog_user_why` | 62 551 | **le « pourquoi »** d'une œuvre dans un top — du texte écrit par le membre |
| `public.users_decouverte` | 98 571 | « ce membre a découvert cette œuvre », avec le top d'origine |
| `public.users_followers` | 524 | suivis — **non migré**, voir §3 |
| `public.users_relations` | 748 | amitiés — **non migré**, voir §3 |
| `movies.catalog` | 365 621 | le catalogue films (337 417 avec id TMDB) |
| `series.catalog` | 8 407 | le catalogue séries (7 852 avec id TMDB) |
| `movies.reviews` / `series.reviews` | 93 / 194 | les avis rédigés |

Deux faits de structure à connaître avant de lire une requête :

- **`personnes.id` = `users_auth.id`.** Il n'y a pas de clé étrangère, mais
  l'égalité est vraie partout. `personnes` sans ligne `users_auth` = **37 006
  invités** : ils ont un pseudo, un top-5 (36 340 tops leur appartiennent), et
  aucun moyen de se reconnecter.
- **Un top-5 n'est pas une table de liaison.** `fives.catalog.tops` est un
  `json[]` de cinq objets `{id, text, description, commentaire}` où `id` est
  l'identifiant du catalogue de l'univers concerné. Le lien membre→œuvre est
  *dans un tableau JSON*, et c'est lui qu'il faut mettre à plat.

### Côté V2 — le pivot est prêt, les membres n'existent pas

| | |
|---|---|
| `sourcing.oeuvre` | **le pivot d'identité** : `(univers, id_tmdb)` unique, `id_tmdb` nullable |
| `sourcing.tmdb_catalog` | l'inventaire — **1 231 681 films et 229 100 séries** |
| `sourcing.oeuvre` (rempli) | **1 231 595 films et 228 429 séries**, tous avec un `id_tmdb` |
| `notation.*` | les axes, rangés sous `oeuvre_id` depuis le lot 12 |
| `admin.admin_user` | le back-office, **pas** les membres du site |

Il n'existe **aucune table de membre en V2**. C'est la moitié du travail : il ne
s'agit pas de convertir un schéma vers un autre, mais d'en écrire un.

---

## 2. La clé d'appariement : l'id TMDB, et rien d'autre

`movies.catalog.source_acquisition` et `series.catalog.source_acquisition`
portent `{"ref":"tmdb","id":1399,...}`, et il existe déjà un index sur
`(source_acquisition->>'id')`. Le chemin d'une œuvre V1 vers la V2 est donc :

```
fives.catalog.tops[].id  →  {movies,series}.catalog.id
                         →  source_acquisition->>'id'   (= id TMDB)
                         →  sourcing.oeuvre (univers, id_tmdb)   → oeuvre.id
```

Les deux univers sont collectés : **la migration n'attend rien du sourcing**,
sinon quelques centaines de fiches (§2.1). **Jamais par le titre**, sauf pour la
traîne décrite au §2.2. Et jamais vers
`id_tmdb` directement dans les tables membres : c'est `oeuvre.id` qui est stocké,
pour la raison écrite dans `012_univers.sql` — les espaces de noms TMDB des films
et des séries sont disjoints.

### 2.1 Ce que ça donne, mesuré contre la production

Seules comptent les œuvres **citées par au moins un membre** : 3 781 séries et
7 195 films distincts, sur les 374 028 lignes de catalogue V1. Le reste du
catalogue V1 n'a pas à être migré — la V2 l'a déjà collecté depuis TMDB.

Les chiffres qui suivent **suivent d'abord les redirections `_301`** (§2.2a) :
c'est ce qui fait la différence entre 89 % et 94 % d'appariement, et c'est la
première chose que l'exporteur doit faire.

Les chiffres qui suivent sont ceux de l'export réellement produit (§4), croisés
avec `sourcing.oeuvre` en production.

| | Séries | Films |
|---|---:|---:|
| fiches canoniques citées, après `_301` | 3 563 | 6 854 |
| … avec un id TMDB | 3 346 | 6 141 |
| … soit, en identifiants TMDB **distincts** | **3 346** | **5 276** |
| … déjà dans `sourcing.oeuvre` (prod) | **3 263** (97,5 %) | **5 148** (97,6 %) |
| … à faire collecter (`tmdb fetch --id`) | 83 | 128 |
| … sans aucun id TMDB (à apparier, §2.2b) | 217 | 713 |
| positions de top exportées (hors doublons) | 258 653 | 65 423 |
| … portant un id TMDB | **94,5 %** | **96,0 %** |
| … perdues faute de collecte | 0,39 % | 0,97 % |

Autrement dit : **dix-neuf positions sur vingt trouvent leur œuvre en V2 sans
rien collecter du tout**, il reste 211 fiches à récupérer à l'unité, et 930
œuvres à apparier ou à créer.

### 2.2 Les quatre cas de perte, et le traitement de chacun

**a) Doublons V1 déjà redirigés — 210 séries, 405 films.** La V1 a fusionné des
fiches en posant `_301 = id de la fiche maître` (« La casa de papel » vit sous
`9129` *et* `134645`). Une citation qui pointe la fiche morte doit suivre la
redirection **avant** l'appariement. Non traité, ce sont deux œuvres V2 là où le
membre en a cité une.

**b) Œuvres sans id TMDB — 219 séries, 713 films** (après `_301`). Des fiches
créées à la main en V1, et elles pèsent : **14 967 citations de séries** et 2 598
de films, « Teen Wolf », « Sherlock » et « How I Met Your Mother » en tête. Deux
traitements, dans cet ordre, et **les deux sont automatiques** :

1. **Le rapprochement.** Titre (`frFR`, `enUS`, `alternative_titles`) normalisé
   — minuscules, accents et ponctuation retirés, articles de tête ignorés —
   contre `sourcing.oeuvre` du même univers, année à ±1 an. Titre normalisé
   identique + année compatible = appariement retenu. Ambiguïté (plusieurs
   candidats, ou année absente des deux côtés) = non retenu, et journalisé.
2. **La création.** Ce qui n'est pas apparié **entre dans la base V2 depuis la
   V1** : une ligne `sourcing.oeuvre` avec `id_tmdb` null, `titre` et `annee`, et
   sa fiche V1 déposée dans `riche_source` sous la source `fivorites_v1`
   (description, réalisateur, acteurs, genres, durée, saisons, affiche). Le pivot
   prévoit explicitement l'œuvre sans identifiant externe — c'est le cas des
   300 séries arabes.

Une œuvre créée ainsi est une œuvre de plein exercice : elle peut être citée,
notée, projetée dans le graphe. Si TMDB la publie un jour, l'`id_tmdb` se
complète par `coalesce` sans rien casser.

**b bis) Un identifiant TMDB pour plusieurs fiches V1 — 854 cas, tous côté
films.** Découvert en produisant l'export : 6 141 fiches de films citées portent
seulement 5 276 identifiants TMDB distincts. Ce sont des doublons que `_301` n'a
jamais reliés. En V2 ils convergent d'eux-mêmes sur un seul `oeuvre_id`, ce qui
est le bon comportement — mais **430 positions de top se retrouvent alors à citer
deux fois la même œuvre**. L'export les marque (`doublon_de`) et les journalise :
la position la mieux classée gagne, l'autre disparaît à l'import.

**c) Citations inexploitables.** 3 585 tops de séries et 1 264 tops de films sans
`id` du tout (`{}` — un cinquième vide dans un top), 232 avec un `id` non
numérique (`"undefined"`), 14 pointant une fiche série supprimée. Elles sont
journalisées et laissées de côté : il n'y a rien à en tirer.

---

## 3. Les pièges mesurés, avant d'écrire une ligne

**Les mots de passe sont des SHA-256 non salés.** `routes/index.js` hache en
`SHA256(password)` — parfois côté client (`req.body.method == "SHA256"`) — et
compare la chaîne telle quelle. Ils ne sont donc **jamais** repris en l'état, et
ce n'est pas urgent : voir plus bas.

**Les emails ne sont pas uniques.** `users_auth.email` l'est (0 doublon), mais
`personnes.emails` est un tableau et **159 adresses apparaissent chez plusieurs
personnes**. La contrainte d'unicité V2 doit porter sur l'email du *compte*, pas
sur le tableau — et les 159 adresses partagées donnent 347 membres distincts,
délibérément (§8) : rien ne dit qu'une boîte mail partagée est une même personne,
et deux tops sous une même adresse sont deux goûts.

**37 006 invités sans compte — ils migrent.** Ils portent 36 340 tops, et un
top-5 est exactement ce que la V2 cherche à exploiter : ils entrent comme membres
sans identifiant, non connectables (aucune ligne dans `membre.identifiant`), avec
leur pseudo et leurs tops. Un compte pourra leur être rattaché plus tard si
l'adresse portée par `personnes.emails` réapparaît à une inscription.

**Le lien entre membres ne migre pas.** Suivis (524) et amitiés (748) restent en
V1 : ce qui intéresse la V2, c'est le voisinage **membre → œuvre → membre**,
reconstruit depuis les tops (§6), pas l'ami déclaré.

**Les tops entrent publics.** 99,8 % d'entre eux portent `privacy = freinds`, une
visibilité qui n'a plus de sens sans graphe d'amis. La valeur V1 est conservée
dans `membre.five.privacy_v1` — on ne perd pas l'intention d'origine — mais la
colonne qui gouverne l'affichage V2 est mise à `public` pour tout le monde. Le
jour où la V2 se dote de vrais réglages de visibilité, `privacy_v1` est encore là
pour les proposer par défaut.

**Les mots de passe ne sont plus un sujet.** Le site n'est pas en production :
les condensats SHA-256 sortent dans `secrets/authentification.jsonl` et
n'entrent pas en V2 tant que l'authentification n'est pas écrite. Quand elle le
sera, le choix reste entier (rehachage à la première connexion, ou « mot de passe
oublié » pour tout le monde) et rien dans la migration ne le contraint.

**110 emails validés sur 32 349.** Le champ `email_valide` n'a quasiment jamais
été rempli. Il ne peut pas servir de critère de tri — ni de base à un envoi.

**Les IP et les sessions ne migrent pas.** `users_auth.ip`, `last_ip`,
`public.sessions` (67 139 lignes) : données personnelles sans usage en V2.

---

## 4. L'export : un JSONL par type, les relations portées par leur propriétaire

Le format est **JSON Lines** (un objet par ligne), pas un gros tableau JSON :
325 000 lignes de tops ne se relisent pas d'un `json.load`, et un import qui
échoue à la ligne 200 000 doit pouvoir reprendre là.

```
export-v1/
  manifest.json              — date, source, instantané V1, comptes et empreintes SHA-256
  utilisateurs.jsonl         — 69 355
  oeuvres-series.jsonl       —  3 563  (les seules œuvres citées)
  oeuvres-films.jsonl        —  6 854
  fives.jsonl                — 67 740  (tops movies + series, « pourquoi » inclus)
  decouvertes.jsonl          — 92 324
  avis.jsonl                 —    287
  a-reconcilier.jsonl        —  4 858  (les cas b, b bis et c du §2.2)
  secrets/authentification.jsonl   — 32 349, mode 600, hors dépôt
```

Produit par [`tools/export_v1.py`](../tools/export_v1.py), en **onze secondes** :

```
sourcing/.venv/bin/python tools/export_v1.py --out ~/travail/export-v1
```

**Les identifiants V1 sont conservés partout** (`v1_id`) : c'est ce qui rend
l'import rejouable et le contrôle possible. Une clé naturelle V2 ne se fabrique
qu'à l'import.

### 4.1 `utilisateurs.jsonl`

```json
{
  "v1_id": 17571,
  "pseudo": "lolo",
  "email": "…@…",
  "emails_secondaires": [],
  "a_un_compte": true,
  "profil": {
    "prenom": null, "nom": null, "bio": "…", "genre": null,
    "date_naissance": null, "avatar": {…}, "socials": [],
    "liens": {"ig": null, "website": null, "youtube": null}
  },
  "compteurs": {"nb_reviews": 0, "note": 0},
  "statut": {"valide": true, "bani": false, "privacy_defaut": "freinds"},
  "acquisition": {"utm_source": null, "utm_campaign": null},
  "dates": {"creation": "…", "derniere_maj": "…", "derniere_connexion": "…"}
}
```

`secrets/authentification.jsonl` reste à part : `{"v1_id", "email", "sha256",
"email_valide"}`. Un fichier, un mode 600, hors dépôt — il ne sert qu'au jour où
l'authentification V2 s'écrit, et il s'efface quand ce jour est passé.

### 4.2 `oeuvres-{series,films}.jsonl`

Deux rôles dans un seul fichier. Pour les 8 621 œuvres qui ont un id TMDB, c'est
**la table de correspondance** — l'import n'a besoin de rien d'autre. Pour les
932 qui n'en ont pas, c'est **la fiche elle-même** : ce sont ces champs-là, et
pas d'autres, qui feront l'œuvre en V2.

```json
{
  "univers": "series",
  "v1_id": 4,
  "id_tmdb": 1399,                // null → la fiche ci-dessous fait foi
  "canonique_v1_id": 4,           // suit _301 si la fiche est redirigée
  "alias_v1_ids": [9129],         // les fiches mortes qui pointaient ici
  "titre": {"frFR": "Game of Thrones", "enUS": "Game of Thrones"},
  "titres_alternatifs": [],
  "annee": 2011,
  "nb_citations": 13817,          // recalculé depuis les tops, pas nb_user_reference
  "valide": true,

  // présent seulement si id_tmdb est null — la matière pour créer l'œuvre
  "fiche": {
    "description": {"frFR": "…"},
    "realisateur": "…", "auteurs": [], "acteurs": [], "productions": [],
    "genres": ["drame", "fantastique"],     // catalog.categorie
    "duree": "…", "langues": [], "distributeurs": [],
    "saisons": [],                          // séries seulement
    "affiche": "…",                         // catalog_medias, defaut = true
    "images": []
  }
}
```

### 4.3 `fives.jsonl` — le cœur

Un objet par top, ses positions à plat, le « pourquoi » joint depuis
`fives.catalog_user_why` sur `(id_five, id_catalog, schemas)`.

```json
{
  "v1_five_id": 69631,
  "user_v1_id": 40865,
  "univers": "series",
  "periode": "life",              // life | moment | year
  "privacy_v1": "freinds",        // conservé pour mémoire ; la V2 importe en public
  "titre": null,
  "positions": [
    {"rang": 1, "oeuvre_v1_id": 4, "canonique_v1_id": 4, "id_tmdb": 1399,
     "titre_saisi": "Game of Thrones", "pourquoi": "…", "commentaire": null},
    {"rang": 3, "oeuvre_v1_id": 746, "canonique_v1_id": 746, "id_tmdb": null,
     "titre_saisi": "The Handmaid's Tale", "pourquoi": null, "commentaire": null},
    {"rang": 4, "oeuvre_v1_id": 9129, "canonique_v1_id": 134645, "id_tmdb": 71446,
     "doublon_de": 2, "titre_saisi": "La casa de papel"},
    {"rang": 5, "statut": "vide"}
  ],
  "dates": {"creation": "…", "derniere_maj": "…"},
  "valide": true
}
```

Quatre choses se lisent dans cet exemple, et chacune est une décision :

- **Le rang est l'ordre du tableau `tops`** — la seule information de classement
  qui existe, et elle disparaît si l'export passe par un `unnest` sans
  `with ordinality`.
- **`oeuvre_v1_id` est ce que le membre a cité, `canonique_v1_id` ce que ça
  désigne** après `_301`. Les deux sortent : l'un pour retrouver la trace, l'autre
  pour apparier.
- **`id_tmdb` à `null` n'est pas un échec** : c'est une œuvre que la V2 devra
  créer, et sa fiche est dans `oeuvres-*.jsonl`.
- **`statut`** (`vide`, `illisible`, `orpheline`) et **`doublon_de`** disent
  pourquoi une position ne donnera pas d'arête. Elles restent dans le fichier :
  un top amputé sans explication est un top qu'on soupçonnera d'un bug d'export.

### 4.4 Les deux autres — découverte, puis avis

```json
{"user_v1_id": 9, "univers": "series", "oeuvre_v1_id": 111, "id_tmdb": 1399,
 "origine": {"from": "fives", "five_v1_id": 116}, "creation": "…"}
```
```json
{"user_v1_id": 17571, "univers": "movies", "oeuvre_v1_id": 5860, "id_tmdb": 550,
 "note": 8, "titre": "…", "texte": "…", "creation": "…"}
```

---

### 4.5 Ce que l'export a appris

Écrire l'export, c'est lire la V1 pour de bon. Cinq choses n'étaient pas dans les
requêtes de comptage :

- **Un « top 5 » n'a pas toujours cinq entrées.** 476 tops en ont plus, jusqu'à
  **118**. Le rang est exporté tel quel ; c'est à l'import de décider s'il tronque
  (et `membre.five_position` ne peut pas contraindre `rang <= 5`).
- **854 identifiants TMDB portés par plusieurs fiches films** (§2.2 b bis), d'où
  430 positions marquées `doublon_de`.
- **2 675 « pourquoi » orphelins** sur 58 251 : le membre a remanié son top, le
  texte est resté attaché à une œuvre qui n'y est plus. Ils sortent dans
  `a-reconcilier.jsonl` plutôt que de disparaître — c'est de la prose écrite par
  quelqu'un.
- **862 tops sans aucune position** : des lignes créées puis vidées. Exportées
  telles quelles, l'import les ignorera.
- **945 membres sans pseudo**, dont il faudra bien afficher quelque chose le jour
  où les tops sont publics.
- **Les descriptions V1 sont du HTML échappé** (`<p>`, `&#39;`). L'export les
  transporte telles quelles — c'est sa fidélité — et c'est à l'import de
  désamorcer avant d'écrire dans `riche_source`.

Le contenu du fichier de reconciliation, tel que produit :

| Type | Lignes | Ce que c'est |
|---|---:|---|
| `pourquoi_orphelin` | 2 675 | du texte de membre sans position |
| `oeuvre_sans_id_tmdb` | 930 | à apparier par titre, puis à créer (§2.2b) |
| `position_orpheline` | 577 | citation vers une fiche V1 disparue (14 fiches) |
| `position_doublon` | 430 | deux positions, une seule œuvre |
| `position_illisible` | 232 | `id` non numérique (`"undefined"`) |
| `fiche_absente` | 14 | la fiche citée n'existe plus du tout |

---

## 5. Ce qu'il faut écrire côté V2 : le schéma `membre`

Rien n'existe. Proposition, calquée sur les conventions déjà en place (un schéma
par couche, le pivot pour toute référence à une œuvre) :

| Table | Contenu |
|---|---|
| `membre.membre` | `id bigserial`, `v1_id` (unique, nullable), pseudo, profil, statut, dates |
| `membre.identifiant` | `membre_id`, `email` unique, `password_hash`, `legacy_sha256`, `email_valide` |
| `membre.five` | `id`, `membre_id`, `univers`, `periode`, `visibilite` (= `public` à l'import), `privacy_v1`, `titre`, dates — unique `(membre_id, univers, periode)` |
| `membre.five_position` | `five_id`, `rang 1..5`, `oeuvre_id → sourcing.oeuvre`, `pourquoi` |
| `membre.decouverte` | `membre_id`, `oeuvre_id`, `origine jsonb`, date |
| `membre.avis` | `membre_id`, `oeuvre_id`, `note`, `texte`, dates |

Ni `suivi` ni `relation` : le lien entre membres ne migre pas (§3), et une table
vide qu'on garde « au cas où » finit toujours par être remplie de travers.

Trois règles qui portent tout le reste :

- **`oeuvre_id` partout, jamais `id_tmdb`.** Une œuvre hors-TMDB doit pouvoir
  être citée dans un top ; c'est précisément ce que le pivot autorise.
- **`v1_id` conservé et unique** sur `membre` et sur `five` : l'import devient
  idempotent (`on conflict (v1_id) do update`), donc rejouable autant de fois
  qu'il le faudra sans dupliquer.
- **`membre` sans ligne `identifiant` est un membre valide**, pas une anomalie :
  c'est le cas des 37 006 invités. Aucune contrainte, aucun écran ne doit
  supposer qu'un membre a un email.

---

## 6. Le voisinage — ce à quoi la migration sert

Le but n'est pas d'avoir des membres en base : c'est d'ouvrir la traversée
**five → personne → five → personne**. Deux membres qui citent la même œuvre sont
voisins ; l'œuvre qu'un voisin cite et que vous ne citez pas est une suggestion.
C'est le filtrage collaboratif de la V1, et c'est la seule chose que les axes de
goût ne savent pas faire — eux comparent des œuvres, pas des gens.

Le graphe l'attend déjà : `doc/graphe-neo4j.md` §9 annonce `:FivMembre` comme la
suite immédiate. La migration en est le premier remplissage.

```
(:FivMembre {membreId})  ──FIV_CITE {rang, periode, pourquoi}──►  (:FivOeuvre)
```

Un seul nœud nouveau, une seule relation. `FIV_CITE` porte le rang (1 à 5), la
période et le « pourquoi » quand il existe — la position dans le top est un
signal de force, pas un détail d'affichage. Le voisinage s'écrit alors :

```cypher
MATCH (m:FivMembre {membreId: $id})-[:FIV_CITE]->(:FivOeuvre)
      <-[:FIV_CITE]-(voisin:FivMembre)-[c:FIV_CITE]->(reco:FivOeuvre)
WHERE NOT (m)-[:FIV_CITE]->(reco)
RETURN reco, count(DISTINCT voisin) AS voisins, avg(6 - c.rang) AS force
ORDER BY voisins DESC, force DESC LIMIT 20
```

⚠️ `:FivPersonne` est **déjà pris** — c'est l'acteur, le réalisateur. Le membre
est `:FivMembre`, et les deux ne se confondent jamais, y compris le jour où un
membre est aussi un réalisateur.

**Les ordres de grandeur sont confortables** : 59 042 membres citant au moins une
série ou un film, ~325 000 relations `FIV_CITE`, face aux 228 452 œuvres et à
leur distribution déjà projetées. Le graphe ne change pas de catégorie.

Trois conséquences qui remontent jusqu'à l'export :

- **Le rang doit survivre au voyage** (§4.3). Sans lui, cinq œuvres citées se
  valent, et une bonne part du signal est perdue à l'import.
- **Un membre est un goût, pas une boîte mail.** Les 347 personnes qui partagent
  une adresse restent 347 membres (§8) : les fusionner mélangerait les tops d'une
  mère et de sa fille, et ferait de leur voisinage une moyenne qui n'est celle de
  personne.
- **Une œuvre non appariée fait un trou dans les ponts.** Une œuvre citée par
  200 membres et absente du pivot, ce sont 200 membres privés d'une arête
  commune — la raison pour laquelle la traîne du §2.2b mérite un traitement, et
  pas un haussement d'épaules.

Rien de tout cela n'oblige à projeter dès la migration : `membre.five_position`
en Postgres suffit à la première recommandation par co-citation. La projection
Neo4j est un lot séparé, qui lira ces tables comme `graphe projeter` lit
`sourcing`.

---

## 7. Le chemin, en six lots

Il n'existe pas de V1 plus récente que l'instantané local du 2021-02-23 : c'est
cet état qu'on migre, et le chemin commence donc à l'exporteur.

| Lot | Ce qu'il fait | Ce qui le déclare fini |
|---|---|---|
| **1** | ✅ **L'exporteur V1** — [`tools/export_v1.py`](../tools/export_v1.py), les sept fichiers du §4 plus le manifest | fait : comptes du manifest = comptes SQL, tops vérifiés à l'identique sur échantillon |
| **2** | ✅ **Migration `membre`** — [`sourcing/migrations/013_membre.sql`](../sourcing/migrations/013_membre.sql), schéma du §5 plus le registre `oeuvre_v1` | fait : passe sur base vide, rejouée de zéro deux fois |
| **3** | ✅ **L'importeur** — `fiv-sourcing import-v1` ([`import_v1.py`](../sourcing/src/fiv_sourcing/import_v1.py)) : œuvres (id TMDB → pivot, rapprochement par titre, création fiche V1 comprise), membres, fives, positions, découvertes, avis | fait : 42 s, rejoué deux fois → zéro différence ; tops vérifiés dans l'ordre V1 |
| **4** | **Jouer sur le serveur** : `db migrate` puis `import-v1` (§7.2) | le rapport de l'import, et les contrôles §7.1 |
| **5** | **Le reliquat de collecte** : `tmdb fetch --id` sur les listes `a-collecter-*.txt` produites par l'import (~211 fiches attendues — les pivots existent déjà, seule la fiche manque) | `a-collecter-*.txt` vides à la passe suivante |
| **6** | **Projection `:FivMembre`** dans le graphe (§6) | la requête de voisinage rend des suggestions |

### 7.2 Sur le serveur

L'export arrive par scp dans `imports/` à la racine du dépôt (le volume
`./imports` du service `sourcing` le monte en `/imports`). Puis :

```
git pull
docker compose --profile cli build sourcing     # les migrations vivent dans l'image
docker compose run --rm sourcing db migrate
docker compose run --rm sourcing import-v1
```

L'import écrit son rapport sur la sortie, et dépose dans `imports/` les listes
de fiches jamais collectées :

```
docker compose run --rm sourcing tmdb fetch --univers series \
    $(sed 's/^/--id /' imports/a-collecter-series.txt)
docker compose run --rm sourcing tmdb fetch --univers movies \
    $(sed 's/^/--id /' imports/a-collecter-movies.txt)
```

⚠️ `imports/secrets/` contient les emails et les condensats V1 : `chmod -R go-rwx`
dès l'arrivée (scp ne préserve pas les droits), et suppression une fois la
migration jouée.

### 7.1 Les contrôles, écrits d'avance

Mesurés sur la répétition locale (base vide + migrations + import complet) :
69 355 membres, 67 740 fives, 324 079 positions, 92 141 découvertes (138
doublons V1 absorbés par la clé), 287 avis, 950 œuvres créées depuis leur
fiche V1. Deux passes de suite : aucun compte ne bouge.

1. `count(membre) = 69 355` — tout le monde entre, invités compris, sans aucune
   fusion.
2. Pour dix membres tirés au sort : leur top-5 V2 affiche **les mêmes titres,
   dans le même ordre**, que la page V1. C'est le seul contrôle qui vaut vraiment.
3. Aucune position ne pointe une œuvre d'un autre univers que son top.
4. Somme des `pourquoi` importés = lignes de `catalog_user_why` movies+series
   moins les citations écartées.
5. Aucun condensat de mot de passe n'a quitté `secrets/` : rien en base V2, rien
   dans un log, rien dans un dump versionné.
6. Le voisinage répond : sur dix membres tirés au sort, la requête du §6 rend au
   moins une suggestion — sinon c'est que les arêtes communes manquent, et le
   §2.2b est à reprendre.

---

## 8. Décisions prises

| | |
|---|---|
| **Tout le monde migre** | 69 355 membres, invités compris, avec tops, « pourquoi », découvertes et avis. Un compte jamais utilisé porte quand même un top-5. |
| **Le lien entre membres ne migre pas** | ni suivis, ni amitiés. Le voisinage se reconstruit par les œuvres (§6). |
| **Les tops entrent publics** | `visibilite = public` pour tous ; la valeur V1 reste dans `privacy_v1`. |
| **Les mots de passe attendent** | le site n'est pas en production ; les condensats restent dans `secrets/`, l'authentification V2 décidera plus tard. |
| **Les adresses partagées ne sont pas fusionnées** | 347 personnes sur 158 adresses : une famille partage une boîte mail, et deux tops différents sous une même adresse sont deux goûts différents. Deux membres, donc. |
| **Les tops « moment » sont gardés** | 3 111 tops en plus des « life » ; ce sont des citations, donc des arêtes, donc du voisinage. |
| **Les pseudos restent tels quels** | 2 034 pseudos portés par 8 351 personnes. Un pseudo n'est pas un identifiant : plusieurs Pierre, c'est le monde normal. |
| **Ce qui n'est pas apparié est créé** | rapprochement par titre d'abord, puis l'œuvre entre en V2 depuis sa fiche V1 (§2.2b). Aucune citation n'est abandonnée faute de fiche. |

### 8.1 Ce que je fixe par défaut, faute de raison de faire autrement

- **La règle de rapprochement** : titre normalisé identique (casse, accents,
  ponctuation, article de tête) **et** année à ±1 an. Un candidat unique passe,
  plusieurs candidats ne passent pas — l'œuvre est créée plutôt que mal
  rattachée. Une erreur d'appariement fait dire à un membre qu'il aime un film
  qu'il n'a pas cité ; un doublon ne dit rien de faux.
- **`export-v1/` vit dans un répertoire de travail, hors dépôt**, et son
  sous-répertoire `secrets/` (emails et condensats SHA-256) s'efface une fois la
  migration jouée. C'est tout ce que recouvrait ma question 7 : ne pas laisser
  traîner un fichier d'emails sur un disque de dev.

---

## 9. Ce que ce plan ne couvre pas

Les univers **livres, BD et musique** (8 985 tops, 17 500 œuvres citées) : le
mécanisme est identique, mais la V2 n'a ni source ni pivot pour eux. Ils sortent
dans l'export — les jeter serait absurde, ils ne coûtent qu'un fichier — et
attendent que leur univers existe.

Le **graphe social** (524 suivis, 748 amitiés), les **notifications** (135 043
lignes), le **mailing** et les **statistiques** d'usage. Le social est une
décision (§8) ; le reste est sans valeur en V2.
