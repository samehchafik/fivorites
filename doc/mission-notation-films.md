# Mission : dupliquer la notation sur les films

Note autonome, rédigée le 2026-08-11, en pendant de
[`etat-des-lieux-notation.md`](etat-des-lieux-notation.md) — qui raconte ce qui
a été fait sur les **séries**. Celle-ci dit ce qu'il faut refaire pour les
**films**, ce qu'il ne faut surtout pas refaire, et dans quel ordre.

Elle contient de quoi reprendre le sujet dans un fil neuf. À lire avec
[`v2-acquisition-series.md`](v2-acquisition-series.md) (la couche 1),
[`v2-notation-axes.md`](v2-notation-axes.md) (la couche 2) et
[`admin.md`](admin.md) (les commandes).

Ordre de lecture si tu es pressé : le §3 est le point dur (l'identité), le §10
donne les lots dans l'ordre. Le §11 liste les quatre mesures à faire **avant**
d'écrire une ligne de code.

---

## 1. Ce que « dupliquer » veut dire ici

La chaîne série va de l'export TMDB au vecteur d'empreinte :

```
export tv_series_ids → tmdb_catalog → collecte (fiche + saisons × 5 langues)
   → raw_source → dossier.py (texte anglais + sha256) → juge GPT → notation.score
   → embed.py (512 dims) → ridge calibrée → notation.weights → vecteur d'œuvre
```

Sur les films, **six des huit maillons se dupliquent presque tels quels**. Les
deux qui résistent sont l'**identité** (§3) et le **barème** (§4). Le reste est
du travail de conduite, pas de conception.

Ce qui est **définitivement acquis** et ne se repaie sur aucun univers :

| Acquis | Où | Transférable ? |
|---|---|---|
| La liste des axes est une **donnée**, pas du code | `notation.rubric.axes`, lue par tout le back | oui, par construction |
| La calibration vise **l'écart-type**, pas la pente | [`weights.py`](../admin/src/fiv_admin/weights.py) | oui — c'est un fait mathématique |
| Le hors-pli seul dit quelque chose (`maeFit` flatte) | `training modeles` | oui |
| Le banc de comparaison de modèles + le contrôle XOR | `training modeles` | oui |
| L'append-only de `notation.score` (jamais d'UPDATE) | migration 003 | oui |
| **Les ancres enseignent la corrélation que la prose interdit** | migration 011 | oui — et c'est le plus précieux |

Ce dernier point vaut deux jours de mesures et environ 40 $ d'appels : sur les
films, **on démarre à l'équivalent de la v3**, pas de la v1. On n'a pas à
réécrire un paragraphe d'indépendance en majuscules pour redécouvrir qu'il ne
sert à rien (§2 de la note série, `empreinte-v2` : « Résultat : rien »).

Ce qui, en revanche, **doit se re-mesurer** — ce sont des faits sur un corpus,
pas sur un algorithme :

| À re-mesurer | Pourquoi ça ne se transfère pas |
|---|---|
| La structure ACP de l'empreinte (halo, dimensions effectives) | dépend du corpus et des ancres, tous deux changés |
| Le MAE hors-pli, le bruit propre du juge (0,37 sur les séries) | dépend de la richesse du dossier, qui change du tout au tout |
| Le plafond de volume (deux plateaux mesurés : 241→298, 346→521) | mesuré sur des dossiers à 8 000 caractères ; ceux des films n'y ressemblent pas |
| Le choix de l'encodeur (trois candidats à 0,006 près) | probablement identique, mais c'est gratuit de le revérifier |

---

## 2. L'asymétrie film/série, en un tableau

C'est le cœur du sujet. Un film n'est pas une série courte : ce qu'on lui
enlève et ce qu'on lui ajoute changent la nature du dossier.

| | Série | Film |
|---|---|---|
| Appels de collecte | 1 fiche + (saisons × 5 langues) ≈ **40** | **1**, point |
| Matière narrative | 10 synopsis d'épisodes + synopsis de saisons | 1 synopsis, ~500–900 caractères |
| Sous-requêtes TV-only | `aggregate_credits`, `episode_groups`, `content_ratings` | remplacées par `release_dates` |
| Sous-requêtes film-only | — | `release_dates`, `lists` |
| `imdb_id` | dans `external_ids` | **champ de premier niveau** de la fiche |
| Enrichissement tiers | Wikidata + Wikipédia + **TVmaze** (~40 % des requêtes) | Wikidata + Wikipédia, **TVmaze disparaît** |
| Wikidata | `P31 = Q5398426`, id TMDB `P4983` | `P31 = Q11424`, id TMDB **`P4947`** |
| Critiques TMDB | **13 sur les 500 plus populaires** (mesuré) | inconnu, probablement bien meilleur — **à mesurer** (§11) |
| Visuels notables | backdrops + stills d'épisodes | backdrops + affiches seulement (pas de stills) |
| Champs propres | `number_of_seasons`, `networks`, `first_air_date` | `runtime`, `tagline`, `budget`, `revenue`, `belongs_to_collection`, `release_date` |
| Volumétrie du catalogue | 228 429 séries | à mesurer par l'export (§11) |

**Les deux conséquences qui commandent tout le reste :**

1. **La collecte des films est un ordre de grandeur moins chère.** Un film =
   une requête. Les 5 000 films les plus populaires se collectent en ~4 minutes
   à 20 req/s, contre des dizaines d'heures pour autant de séries. Le §8.4 de
   la note série — « 502 exemples pour 512 dimensions, le pire régime » — se
   résout donc *par le volume* sur les films, ce qui n'était pas envisageable
   sur les séries.

2. **Le dossier film est nu.** Retirer les synopsis d'épisodes et de saisons,
   c'est retirer les deux tiers du texte. Un dossier film sans Wikipédia, c'est
   un titre, des genres, des mots-clés et un paragraphe — soit à peu près le
   « dossier maigre » que le barème v3 apprend au juge à refuser de noter.
   **Wikipédia n'est pas un enrichissement optionnel sur les films : c'est le
   dossier.** D'où l'inversion d'ordre du §10.

---

## 3. Le point dur : l'identité

### Le problème

`notation.score`, `notation.training_run`, `notation.media_caption` et
`sourcing.video` portent toutes une clé `id_tmdb integer references
sourcing.tmdb_catalog (id)`. Et `sourcing.tmdb_catalog` a `id` pour clé
primaire, sans autre qualification.

Or **les identifiants TMDB de films et de séries vivent dans deux espaces de
noms disjoints** : `1399` désigne *Game of Thrones* côté `/tv` et un tout autre
film côté `/movie`. Charger l'export des films dans `tmdb_catalog` en l'état
écraserait des lignes de séries, et une note de film irait se ranger sous une
série. Ce n'est pas un risque théorique : c'est ce qui se passe au premier
`insert ... on conflict (id)`.

### Trois issues

*(Écrit avant la décision. Le lot A a retenu l'option C et l'a appliquée le
2026-08-12 — migrations `sourcing/012_univers.sql` et
`admin/012_notation_oeuvre.sql`. Un point n'avait pas été anticipé : le pivot
ne pouvait pas garder de clé étrangère vers `tmdb_catalog`, sous peine de faire
échouer `tmdb fetch --id` sur une série collectée avant d'entrer dans l'export.
Voir le §5 du dictionnaire de données.)*

| Option | Ce qu'elle coûte | Ce qu'elle laisse |
|---|---|---|
| **A.** `(univers, id_tmdb)` partout | 5 migrations, +1 colonne dans 5 tables, toutes les jointures à doubler | une clé composite dans chaque requête, et toujours rien pour les œuvres hors TMDB |
| **B.** Tables parallèles (`tmdb_catalog_film`, `score_film`…) | aucune migration des tables existantes | deux chaînes à maintenir en parallèle, et un troisième univers = une troisième chaîne |
| **C.** **Le pivot `sourcing.oeuvre`** | 1 migration, `id_tmdb` → `oeuvre_id` dans 4 tables, ~120 occurrences d'`id_tmdb` à reprendre côté admin | une seule clé, tous univers, y compris les œuvres sans TMDB |

**Recommandation : C.** Ce n'est pas un arbitrage d'esthétique, c'est ce que la
migration `007_oeuvre.sql` a écrit noir sur blanc en la créant :

> C'est aussi, par anticipation, l'`oeuvre_id` que la couche 2 (notation)
> attend.

La table existe, elle porte déjà `univers` (`series | movies | books | bd |
musics`), ses index uniques sont déjà partiels par univers, et
`riche_source.oeuvre_id` la référence déjà. Passer par A reviendrait à payer
une migration des tables de notation maintenant pour en repayer une seconde le
jour où le pivot devient obligatoire — c'est-à-dire au premier film khaleeji
hors TMDB, exactement le cas qui a fait naître `oeuvre`.

`tmdb_catalog` garde par ailleurs sa propre correction, indépendante du choix :
clé primaire `(univers, id)`, et `first_air_date` renommée ou doublée par
`release_date` — l'export film ne porte pas les mêmes champs (`original_title`
et non `original_name`, plus un booléen `video`).

### Le volume de données concerné est dérisoire

~3 000 lignes de `score`, autant de `training_run`, quelques milliers de
`media_caption` et de `video`. La migration est instantanée ; c'est le code qui
coûte, pas les données. **Et elle se fait entièrement sur les séries, sans un
seul film en base** — c'est le lot A du §10, et il devrait partir en premier
précisément pour ça : il est testable tout de suite, contre l'existant.

---

## 4. Le barème film

### La question qui doit être tranchée avant d'écrire le prompt

Le prompt `empreinte-v3` commence par « Read the dossier about a **TV series** »
et ses 24 ancres sont 24 séries. On ne peut pas le tendre tel quel à un film.

Mais la vraie question n'est pas de le traduire : c'est de savoir si
**`joie = 8` sur un film veut dire la même chose que `joie = 8` sur une série.**

Deux barèmes ancrés sur deux corpus disjoints produisent deux échelles
étrangères l'une à l'autre. Or le programme de R&D (§4.5.1.5) demande que
l'empreinte classe **les objets et les membres dans le même espace**, et
l'empreinte d'un membre se déduit de la liste des objets qu'il aime — laquelle
mélangera films et séries dès le premier utilisateur. Une distance cosine entre
un film noté sur une échelle et une série notée sur une autre ne veut rien dire.

| | Deux barèmes (`empreinte-film-v1`) | **Un barème mixte (`empreinte-v4`)** |
|---|---|---|
| Écriture | copie + 24 ancres films | +24 ancres, retirer « relative to television series » |
| Comparabilité films/séries | **à établir par un pont, en permanence** | acquise par construction |
| Coût immédiat | nul | re-noter les 502 séries : **~0,50 $** sans légendes, ~2 $ avec |
| Risque | un pont qui dérive à chaque révision d'un des deux barèmes | prompt plus long (48 ancres), dérive possible des notes séries |

**Recommandation : le barème mixte.** Le coût de re-notation est celui d'un
café, et il achète en prime une mesure gratuite : l'écart entre les notes séries
v3 et v4 sur les mêmes 502 œuvres dit exactement ce que l'arrivée des ancres
films a déplacé.

Le test qui tranche, si le doute persiste : noter 60 films sous les deux
barèmes et comparer les distributions par dimension. Si elles se superposent, le
barème mixte ne coûte rien ; si elles divergent, c'est que l'échelle *était*
dépendante de l'univers — et le pont aurait été une fiction.

### Les ancres films proposées

Construites selon la règle apprise en v3, qui n'est pas « aucun titre partagé »
mais **« aucune uniformité de ton en haut d'échelle »** : chaque dimension a au
moins une ancre haute dans un registre léger et une dans un registre grave.

| Dimension | 1 | mi-échelle | haut | 10 |
|---|---|---|---|---|
| `joie` | Come and See | Lost in Translation (4) | Amélie (8) | Singin' in the Rain |
| `reve` | Spotlight | Apollo 13 (2) | Spirited Away (9) | Pan's Labyrinth |
| `tristesse` | Airplane! | Toy Story 3 (6) | Up (8) | Manchester by the Sea |
| `peur` | My Neighbour Totoro | Gremlins (5) | Jaws (8) | The Exorcist |
| `reflexion` | Fast Five | Ocean's Eleven (3) | The Truman Show (8) | 2001: A Space Odyssey |
| `action` | 12 Angry Men | Jurassic Park (6) | Raiders of the Lost Ark (8) | Mad Max: Fury Road |

Vérifications faites, ce sont celles qui avaient manqué en v1 :

- 24 titres distincts, aucun ancre de deux dimensions ;
- hauts de `tristesse` : *Up* (chaleureux, drôle) et *Manchester by the Sea*
  (grave) — le motif qui avait effondré `tristesse × peur` à 0,84 est cassé
  d'avance ;
- hauts de `peur` : *Jaws* (exaltant, sans deuil) et *The Exorcist* (grave) ;
- hauts de `reflexion` : *The Truman Show* (comédie) et *2001* (froid) ;
- hauts de `action` : *Raiders* (jubilatoire) et *Fury Road* (implacable) ;
- hauts de `reve` : *Spirited Away* (lumineux) et *Pan's Labyrinth* (sombre).

Ces ancres sont **une proposition, pas une mesure**. Leur validation est la
même que celle de la v3 : ACP sur les 50 premiers films notés, information
propre par dimension, corrélation `tristesse × peur`. Si elle ressort au-dessus
de 0,75, c'est le haut d'échelle qu'il faut relire, jamais la prose.

---

## 5. Le dossier film

[`dossier.py`](../admin/src/fiv_admin/dossier.py) se décline section par
section. Ce qui change :

| Section série | Film |
|---|---|
| `TITLE` / `ORIGINAL TITLE` | `title` / `original_title` (mêmes clés, autres noms) |
| `FACTS: first aired…, N seasons, N episodes, network` | `released`, `runtime`, `country`, `production companies`, `collection` |
| `GENRES`, `KEYWORDS` | identiques |
| `OVERVIEW` | identique — mais c'est désormais **le seul texte natif** |
| `WIKIPEDIA (en)` | identique, et **devient la section principale** |
| `VIEWER REVIEWS` | identique — et potentiellement enfin utile (§11) |
| `MEDIA` (légendes) | backdrops + affiches ; **pas de stills d'épisodes** |
| `SEASON OVERVIEWS` | supprimée |
| `EPISODE SYNOPSES` | supprimée |
| — | **`TAGLINE`** : une ligne, écrite pour dire le ton. Gratuite, à ajouter. |

Trois réglages à revoir, et un qui devient sans objet :

- **`MIN_CHARS = 400`** — calibré sur des dossiers séries. Un film sans
  Wikipédia frôlera ce seuil en le franchissant : il passera le garde-fou sans
  porter la moindre information de ton. C'est le réglage le plus dangereux du
  lot, et le §11.3 dit comment le fixer sur des données plutôt qu'à vue.
- **`WIKIPEDIA_MAX_CHARS = 6000`** — sur les films, la contrainte de budget
  disparaît (plus d'épisodes pour la concurrencer). 8 000 à 10 000 est
  probablement le bon ordre, à valider par la longueur médiane des articles.
- **`EPISODE_SAMPLE`, `SEASON_OVERVIEW_MAX_CHARS`** — sans objet.
- **`embed.MAX_CHARS = 12 000`** — la troncature qui a coûté Docteur House
  (§5 de la note série) ne mordra plus : un dossier film complet tiendra
  largement dessous. **L'ordre des sections reste néanmoins celui de la v3** —
  ce qui parle de l'œuvre avant ce qui raconte l'intrigue — parce que rien ne
  garantit qu'un article de 40 000 caractères ne se présentera pas.

Le déterminisme, lui, ne se négocie pas : même sélection, même texte, même
sha256. C'est ce qui permet de dire si une divergence vient du modèle ou du
dossier.

---

## 6. La collecte

Fichier par fichier, ce qu'il faut ajouter — rien de ce qui suit n'est une
réécriture, tout est un second cas :

**[`export.py`](../sourcing/src/fiv_sourcing/sources/tmdb/export.py)**
`export_url()` → `movie_ids_MM_DD_YYYY.json.gz` ; `load_catalog()` lit
`original_title` au lieu d'`original_name` ; l'upsert vise `(univers, id)`.
Gratuit, aucun quota.

**[`client.py`](../sourcing/src/fiv_sourcing/sources/tmdb/client.py)** un
`MOVIE_APPEND` à côté de `SERIES_APPEND` — et c'est **la seule décision à
prendre largement, une fois**, puisque le brut protège des changements de
dérivation, pas de collecte :

```
alternative_titles, credits, external_ids, images, keywords,
recommendations, release_dates, reviews, similar, translations,
videos, watch/providers
```

Soit 12 sur les 20 autorisées. `aggregate_credits` et `episode_groups`
n'existent pas côté film ; `content_ratings` devient `release_dates` (qui porte
les classifications par pays). `lists` reste dehors — la V1 l'appelait sans
jamais le lire. Les deux paramètres `include_image_language: "fr,en,null"` et
`include_video_language: "fr,en,null"` se reprennent tels quels : la leçon du
2026-08-11 (10 → 17 séries avec vidéos) vaut à l'identique.

**[`collect.py`](../sourcing/src/fiv_sourcing/sources/tmdb/collect.py)**
`collect_movie()` = `collect_series()` sans la boucle de saisons. Une réponse,
une ligne de `raw_source`, `kind = 'movie'`. La liste
`tmdb_season_languages` ne s'applique pas : le synopsis anglais arrive dans
`translations`, appendu à l'appel unique.

**[`enrich.py`](../sourcing/src/fiv_sourcing/enrich.py)** Wikidata sur `P4947`
au lieu de `P4983`, balayage `P31 = Q11424` au lieu de `Q5398426`, Wikipédia
inchangé, **TVmaze retiré** — il ne connaît pas les films. L'`imdb_id` est plus
facile à obtenir qu'en série : il est au premier niveau de la fiche film, pas
dans `external_ids`.

**[`video.py`](../sourcing/src/fiv_sourcing/video.py)** la colonne `saison`
reste nulle ; le reste est identique, `videos-check` compris.

**[`changes.py`](../sourcing/src/fiv_sourcing/sources/tmdb/changes.py) /
[`backfill.py`](../sourcing/src/fiv_sourcing/sources/tmdb/backfill.py)**
l'endpoint des changements a sa variante `/movie/changes`. Même logique.

**Côté CLI**, un `--univers movies` (défaut `series`) sur `tmdb export`,
`tmdb fetch`, `enrich`, `videos`, `training note`. Pas de commandes nouvelles :
un univers n'est pas une commande, c'est un paramètre.

---

## 7. L'admin et le front : déjà à moitié écrits

Bonne surprise, et elle est documentée dans
[`media.py`](../admin/src/fiv_admin/media.py) :

```python
"movie": Media(key="movie", label="Films", catalog_table=None, kind="movie", …)
```

Le sélecteur d'univers existe, l'API répond déjà « cet univers n'est pas encore
collecté », et le front l'affiche. Le commentaire du fichier annonce la
manœuvre : « le jour où le catalogue des films arrive, il suffit de renseigner
`catalog_table` ». C'est vrai à un objet près :

- **`admin.tv_card`** a besoin de son pendant `admin.movie_card` — mêmes
  colonnes, `release_date`/`runtime` au lieu de `first_air_date`/
  `number_of_seasons`, source `kind = 'movie'`. Et les deux requêtes qui la
  nomment en dur ([`catalog.py`](../admin/src/fiv_admin/catalog.py),
  [`routes/training.py`](../admin/src/fiv_admin/routes/training.py:247))
  doivent la choisir par univers.
- Les chemins où `part_kind is None` (le panneau des saisons, les compteurs de
  couverture par langue) sont prévus dans le type mais jamais exercés : c'est
  là que les surprises attendent.
- Les index de la migration `001_admin.sql` portent sur
  `split_part(source_id, '/', 1)` — la forme `1399/s2` des saisons. Sans
  parties, ils ne servent à rien aux films, et il n'en faut pas de nouveaux.

Côté React, `SeriesCard`/`SeriesGrid`/`SeriesModal` deviennent des composants
d'œuvre ; `SeasonPanel` se masque ; `VideoTab`, `TrainingTab`, `RichPanel` et
`AxisVector` sont déjà agnostiques.

---

## 8. Ce qu'il ne faut pas refaire

La note série a un §9 « erreurs de méthode ». Les voici transposées, en dur :

**Ne pas livrer une section avant d'avoir compté ce qu'elle contient.** La
section `VIEWER REVIEWS` a été écrite, testée et déployée pour 13 séries sur
500. Sur les films, la même section est *probablement* rentable — mais
« probablement » est exactement le mot qui a coûté trois tours. Compter d'abord
(§11.2), coder ensuite.

**Ne pas relancer les quatre hypothèses éliminées.** Volume, encodeur,
calibration, forme du modèle : elles ont été tranchées. Sur les films, le
premier réflexe en cas de plafond doit être **le diagnostic des voisins**
(§8.3 de la note série, jamais construit : une vingtaine de lignes, aucun appel
payant), pas une cinquième relance du banc de modèles.

**Ne pas enrichir après avoir noté.** C'est l'erreur la plus coûteuse de
l'histoire série : `enrich` avançait par identifiant, `training note`
sélectionnait par popularité, et **43 œuvres notées sur 521** avaient un
enrichissement. Sur les films, où Wikipédia *est* le dossier, la même erreur ne
donnerait pas un plafond : elle donnerait des `null` partout. L'enrichissement
passe donc **avant** la notation dans l'ordre des lots, sans exception.

**Ne pas se disperser.** Les vidéos et les critiques sont des chantiers
légitimes. Ils ne sont pas sur le chemin critique de la notation film.

---

## 9. La prédiction qui rend cette mission intéressante

Le §7 de la note série se termine sur trois confirmations indépendantes que
**le ton n'est pas dans le texte encodé** : Lucifer (comédie dans le jeu, pas
dans le synopsis), Docteur House (réflexion dans l'article, jamais lue), et
l'axe `humour` bloqué à 1,25.

Les films ont une chance sérieuse de faire mieux, pour une raison structurelle :
**l'accueil critique d'un film est écrit, et il est dans Wikipédia.** Un article
de film porte une section « Critical reception » — des phrases qui disent
littéralement « hilarant », « glaçant », « bouleversant ». C'est précisément la
matière de ton que la section `VIEWER REVIEWS` cherchait sans la trouver côté
télévision.

Autrement dit : **l'univers film n'est pas seulement une duplication, c'est le
banc d'essai du plafond des séries.** Si la régression film descend nettement
sous 0,90 de MAE hors-pli avec le même encodeur et le même modèle, alors le
plafond série vient bien de la pauvreté du dossier, et pas de l'encodeur — ce
que ni le volume, ni les trois encodeurs, ni les quatre modèles n'ont su dire.

C'est une hypothèse. Elle se mesure en un lot.

---

## 10. Les lots, dans l'ordre

L'ordre n'est pas négociable sur trois points : A avant tout (sinon deux
migrations), C avant F (sinon les 43/521 recommencent), et §11 avant A.

| # | Lot | Contenu | Effort | Débloque |
|---|---|---|---|---|
| **0** | Les mesures | §11 — quatre sondes, aucune ligne de code | ½ j | tout le dimensionnement |
| ~~**A**~~ | ~~L'identité~~ | **fait le 2026-08-12** — `tmdb_catalog (univers, id)` ; `oeuvre_id` dans `score`, `training_run`, `media_caption`, `embedding`, `video`, `video_scan` | — | **tout**, et validé sur les séries seules |
| ~~**B**~~ | ~~La collecte~~ | **fait le 2026-08-12** — export films, `MOVIE_APPEND`, `collect_movie`, `--univers` sur `export`/`fetch`/`dates`/`changes`/`backfill`. Aucune migration : `tmdb_catalog` portait déjà l'univers, `raw_source.kind` est du texte libre | — | la collecte tourne ; l'affichage attend `movie_card` |
| **C** | L'enrichissement | Wikidata `P4947`/`Q11424`, Wikipédia, TVmaze retiré | 1 j | le dossier film |
| **D** | Le dossier | `build_dossier` variante film, `TAGLINE`, `MIN_CHARS` recalibré | 1 j | la notation |
| **E** | Le barème | `empreinte-v4` mixte, 48 ancres, re-notation des 502 séries (~2 $) | 1 j | l'espace commun |
| **F** | La notation | `training note --univers movies -n 2000`, puis `training poids` | 0,5 j + ~8 $ | les premières mesures |
| ~~**G**~~ | ~~Le front~~ | **fait le 2026-08-12** — `admin.movie_card` aux colonnes de `tv_card`, `media` sur la grille, la fiche et l'état de projection ; l'accordéon des saisons se saute sur un univers sans parties | — | l'exploitation |

Après F, la première chose à produire est **le tableau du §3 de la note
série** — ACP, dimensions effectives, `|r|` moyen, paire la plus liée — et à
volume comparable. C'est le seul verdict qui compte, et la note série rappelle
pourquoi : sur 52 œuvres, l'empreinte paraissait effondrée ; sur 502, elle était
indistinguable des anciens axes. **Ne pas juger un barème film sur 50 films.**

---

## 11. Les quatre mesures à faire avant d'écrire du code

Toutes gratuites, toutes en moins d'une demi-journée.

**11.1 — La volumétrie.** ~~Une commande, aucun quota~~ — **mesurée le
2026-08-12** :

| | séries | films |
|---|---|---|
| Œuvres à l'inventaire | 228 953 | **1 231 681** |
| Export compressé | 5,0 Mo | 27,5 Mo |
| Appels de collecte par œuvre | ~40 | **1** |
| Ordre de grandeur du catalogue entier | — | **5,4 ×** les séries |

Les deux écarts jouent en sens contraire, et c'est le rapport qui compte :
**40 fois moins cher par œuvre, 5,4 fois plus d'œuvres**, donc environ **sept
fois moins de requêtes** pour le catalogue entier. Mesuré sur les 500 premiers
films : 500 requêtes, 500 réussites, aucun 429 à 20 req/s, **6,3 films/s**. Au
même débit, le catalogue entier demande de l'ordre de **55 heures** — contre
des semaines côté séries.

Et pour la notation, ce qui compte n'est pas le fond de catalogue mais la tête :
les 5 000 films les plus populaires se collectent en **treize minutes**.

**11.2 — Les critiques.** Collecter 500 films populaires (500 requêtes, ~30
secondes) et poser la question qui n'a pas été posée pour les séries :

```sql
select count(*) filter (where jsonb_array_length(payload -> 'reviews' -> 'results') > 0),
       count(*)
from raw_source where source = 'tmdb' and kind = 'movie';
```

Sur les séries : **13 sur 500**. Si les films dépassent 100, la section
`VIEWER REVIEWS` change de statut — d'appoint documenté à source principale de
ton, et le §9 devient testable tout de suite.

**11.3 — La longueur du dossier.** Sur les mêmes 500 films, assembler le
dossier (gratuit, aucun LLM) et sortir la médiane et le premier décile de sa
longueur, **avec et sans Wikipédia**. C'est ce qui fixe `MIN_CHARS` sur une
donnée plutôt qu'à vue, et qui chiffre le coût réel du lot C. Repère série :
~8 000 caractères.

**11.4 — Le taux de `null`.** Noter 50 films sous le barème v3 traduit
(~0,05 $) et compter les `null` rendus par dimension. Le barème v3 *sait* dire
« le dossier ne permet pas de trancher » — c'est sa v2 qui l'a appris. Un taux
de `null` élevé sur des dossiers films non enrichis est le signal le plus net
qu'on puisse obtenir pour l'ordre des lots, et il coûte cinq centimes.

---

## 12. Ce qui reste ouvert après cette note

1. **L'échelle commune films/séries** — tranchée par le test du §4, pas par
   l'argument. Tant qu'elle ne l'est pas, aucune distance cosine inter-univers
   n'est légitime.
2. **Le §5 de [`v2-notation-axes.md`](v2-notation-axes.md)**, toujours écrit en
   « position + tolérance ». Il était déjà à réécrire pour les séries ; les
   films ne changent rien à cette dette, ils la rendent plus urgente.
3. **Les autres univers.** `oeuvre.univers` annonce `books | bd | musics`. Si
   le lot A est fait comme au §3, le troisième univers coûtera le lot B et rien
   d'autre — c'est le seul critère qui dise si le lot A a été bien fait.
4. **La collection** (`belongs_to_collection`) est un objet que les séries
   n'ont pas : huit *Harry Potter* forment un arc que le graphe de
   recommandation devrait connaître. Hors périmètre de la notation, mais à ne
   pas perdre.
