# Acquisition des données séries — plan de travail

> Suite opérationnelle de `v2-sourcing-series.md` (dépôt V1), qui décrit *quoi*
> collecter et pourquoi. Ce document-ci décrit *comment*, dans quel ordre, et ce
> qui a déjà été décidé.
>
> État : lots 1 et 2 livrés — le catalogue complet est inventorié et la collecte
> de masse tourne. Lots 3 à 5 à faire ; du lot 6, `/tv/changes` est déjà là.

---

## 1. L'objectif, en une phrase

Produire par série un **dossier de notation** — assez de texte descriptif fiable
pour que le LLM sorte 6 nombres qui tiennent la route — et assez de faits
structurés pour calculer les facettes d'usage.

Tout le reste (colonnes, incrémental, sources tierces) est au service de ça.

## 2. Trois constats qui commandent l'ordre des travaux

**La question qui bloque tout est la matière textuelle, pas la collecte.**
Tant qu'on ne sait pas jusqu'où dans la queue de popularité il reste de quoi
noter, on ne sait ni quel périmètre viser, ni si Wikipédia est optionnel ou
indispensable, ni combien coûtera la notation. Le premier livrable de fond est
donc un **rapport de couverture**, pas un catalogue.

**Le coût réel n'est pas TMDB, c'est la notation.** Un appel pour la fiche, plus
un appel par saison et par langue — soit une quarantaine de requêtes pour une
série de huit saisons en cinq langues. Sur les 228 454 séries du catalogue,
l'ordre de grandeur est de 2 millions de requêtes : une trentaine d'heures de
machine et zéro euro. Six axes par LLM sur 228 454 séries, c'est un budget.

D'où la forme qu'a prise la sélection, une fois le lot 2 mesuré : **aucun filtre
à l'acquisition, le périmètre se tranche en aval** (§3). La V1 filtrait à
l'entrée sur des critères qui n'en étaient pas (« pas adulte » et « au moins une
affiche ») ; filtrer sur `popularity` aurait été pire — la mesure du lot 2
montre que ça sous-représenterait d'un facteur six les catalogues en écriture
arabe.

**Le brut ne protège que de la dérivation.** Conserver le JSON permet de réviser
un axe ou d'ajouter une facette sans réseau. Mais ajouter un sous-appel à
`append_to_response` impose de retélécharger le catalogue entier. Corollaire :
cette liste se décide **une fois, largement, avant le grand run**. C'est la seule
décision non rejouable du projet.

## 3. Décisions prises

| Sujet | Décision |
|---|---|
| **Catalogue V1** | **Table rase.** On re-collecte tout depuis TMDB sur l'architecture cible. La V1 n'est plus une dépendance du chantier : ni son catalogue, ni son pipeline, ni son schéma. Le seul actif à ne pas perdre reste les fives utilisateurs (§5.3 du doc de sourcing), qui se raccorderont plus tard par `id_tmdb`. |
| **Filtrage à l'acquisition** | **Aucun**, mesure du lot 2 à l'appui. `popularity` est une métrique d'usage du *site* TMDB, dont le public est très majoritairement occidental : un seuil à 5 ne retiendrait que 54 des 5 560 séries en écriture arabe, alors que leur popularité médiane est comparable à celle du reste du catalogue. On collecte tout ; le tri se fait en aval, sur des données complètes. |
| **Périmètre de notation** | Non décidé — **mesuré** au lot 5. Le rapport de couverture donne la courbe « matière disponible × popularité » ; le seuil se lit dessus. |
| **Langues des saisons** | fr, en, es, ar, tr — un appel par saison **et par langue**, c'est le poste de coût dominant. La raison : `language=` traduit aussi l'`overview` de chaque épisode, alors que l'endpoint `translations` d'une saison ne porte que sur la saison elle-même. Réglable par `TMDB_SEASON_LANGUAGES` ; à confirmer par une requête avant la passe complète, le facteur est de cinq (§5, lot 2). |
| **Langage** | Python 3.12, **vendorisé** dans `sourcing/vendor/python`. Aucune dépendance à un Python système : le Makefile n'appelle jamais `uv run`, et un garde-fou échoue si la venv dérive. |
| **Exécution** | **Postgres tourne toujours sur l'hôte, jamais en conteneur** — poste de dev comme serveur. Seule l'application est conteneurisée, et seulement sur le serveur : en local elle tourne sur le Python de `vendor/`. Mise en place serveur : [`serveur-debian11.md`](serveur-debian11.md). |
| **Base** | Postgres local de la machine, rôle et base `fivorites_v2`. **Une seule base pour tout le projet, un schéma par domaine.** **Pas de Docker.** |
| **Licence TMDB** | À lever avant le grand run, pas avant le prototype. Explorer 300 séries ne pose aucun problème d'usage ; construire un produit commercial dessus, si. À traiter en parallèle. |

## 4. Architecture

Une base, `fivorites_v2`. Un schéma par couche — les frontières sont nettes sans
que rien ne soit éparpillé, et une jointure entre couches reste une jointure
ordinaire.

```
base fivorites_v2
│
├─ schéma sourcing ── COLLECTE ─────────────────────────┐
│    raw_source(source, kind, source_id, lang,          │
│               fetched_at, http_status, payload, sha)  │
│    fetch_state(…, last_fetched_at, last_changed_at,   │
│                priority, attempts, last_error)        │
│    tmdb_catalog(id, original_name, popularity,        │
│                exported_on, changed_at)               │
│    → append-only, jamais retouché, jamais interprété   │
│                                                       │
│    series_source(id_tmdb, source, lang, content,      │
│                 media, resolved_by, content_chars)    │
│    → dérivée, reconstructible depuis raw_source       │
│  ─────────────────────────────────────────────────────┘
│              ↓  dérivation hors ligne, rejouable, sans réseau
├─ schéma catalog ── COUCHE 1 : FAITS ──────────────────┐
│    series(id, id_tmdb unique, imdb_id, wikidata_id, …)│
│    series_locations(id_series, lieu, type, source)    │
│  ─────────────────────────────────────────────────────┘
│              ↓  notation LLM, rejouable
├─ schéma scores ── COUCHE 2 : AXES ────────────────────┐
│    series_scores(id_series, axe, valeur, confiance, …)│
│  ─────────────────────────────────────────────────────┘
│              ↓  requêtes
└─ COUCHE 3 : FACETTES ── calculées, jamais stockées

public.schema_migrations — l'historique, qui vaut pour la base entière
```

Seul `sourcing` existe aujourd'hui ; `catalog` et `scores` arrivent aux lots 4
et suivants. La connexion pose le `search_path`, donc le code applicatif écrit
`raw_source` sans préfixe ; les migrations qualifient tout explicitement.

`tmdb_catalog` est à part : ce n'est pas du brut, c'est un **inventaire** — une
ligne par série connue de TMDB, et non une ligne par téléchargement. Il vient de
l'export quotidien, un fichier public qui ne consomme aucun appel d'API, et il
sert de base de sondage : volumétrie réelle, déciles de popularité, et détection
des séries disparues (`exported_on` qui décroche).

`series_source` est l'autre exception, dans l'autre sens : c'est de la
**dérivation**, posée dans `sourcing` parce qu'elle décide de ce qu'il reste à
aller chercher. Une ligne par (série, source, langue) répond à une question que
le brut ne sait pas poser — « pour cette série, qu'a-t-on trouvé ailleurs, et
combien ça pèse ? ». Le payload, lui, continue d'aller dans `raw_source`, et la
fraîcheur dans `fetch_state`, toutes deux déjà génériques : une source
`wikipedia` n'y demande aucune colonne nouvelle.

`resolved_by` mérite un mot. Elle enregistre **par quel chemin** le raccordement
s'est fait — `p4983`, `p345`, `sitelink`, `title`. Sans elle, le taux de
résolution par chemin est une étude à refaire à chaque fois ; avec elle, c'est un
`group by`. La mesure du 2026-08-06 est là pour ça : l'entrée par identifiant
TMDB ne rapporte que 6 séries de langue arabe et 8 de langue turque là où
l'entrée par IMDb échoue — un chiffre à revérifier sans rejouer la collecte.

Deux tables portent à elles seules la correction des trois faiblesses de la V1 :
le brut jeté dans des fichiers jamais relus, l'état incrémental dans trois JSON
sur disque, et l'absence de fraîcheur par item.

`raw_source` est dédupliqué par empreinte SHA-256 du payload canonicalisé :
rejouer une collecte sur une source inchangée n'écrit rien. `fetch_state`
distingue `last_fetched_at` (quand on a regardé) de `last_changed_at` (quand ça
a bougé) — deux questions auxquelles la V1 ne savait répondre ni l'une ni
l'autre.

*Limite connue* : TMDB recalcule `popularity` quotidiennement, donc un
rafraîchissement journalier produira une empreinte différente même sans
changement réel. Volontairement laissé tel quel — filtrer des champs dans
l'empreinte reviendrait à interpréter le brut. Ça se traite au niveau de la
politique de rafraîchissement (lot 6).

## 5. Les lots

### ✅ Lot 1 — Socle *(livré)*

Projet `sourcing/` : Python vendorisé, migrations, client HTTP avec limiteur et
reprise sur erreur, client TMDB, collecte série + saisons, CLI, 18 tests.

Écarts assumés avec la V1 dans `append_to_response` :

- **ajoutés** — `external_ids` (les clés de jointure vers Wikidata et Wikipédia,
  sans lesquelles toute la couche géographique est impossible),
  `content_ratings`, `watch/providers`, `aggregate_credits`
- **retirés** — `releases` et `lists`, qui sont des endpoints *films*. La V1 les
  demandait sur des séries depuis 2017 : deux sous-requêtes pour rien.

*Critère d'acceptation, vérifié* : `tmdb fetch --id 1399` écrit dans
`raw_source` ; relancé, il redemande à TMDB mais n'écrit aucune ligne, tout en
faisant avancer `last_fetched_at`.

### ✅ Lot 2 — Catalogue et collecte de masse *(livré)*

L'export quotidien `tv_series_ids_MM_DD_YYYY.json.gz` contient `id`,
`original_name` **et `popularity`** pour tout le catalogue : base de sondage
gratuite, sans une seule requête d'API. `tmdb export` la charge dans
`tmdb_catalog`, `tmdb catalog` en donne la volumétrie et les déciles de
popularité, `tmdb backfill` collecte l'ensemble en reprenant là où la passe
précédente s'est arrêtée (`--limit`, `--concurrency`, `--order`,
`--refresh-after`, `--dry-run`).

**Ce que la mesure a changé au plan.** L'échantillon stratifié de 300 séries
devait servir à décider quoi collecter. La répartition par écriture a tranché
autrement : `popularity` n'est pas un filtre acceptable (§3), donc il n'y a plus
de sélection à faire à l'acquisition — on prend tout. L'échantillon garde son
rôle en aval, pour la calibration des axes et le rapport de couverture du
lot 5.

**Volumétrie mesurée** : 228 454 séries à l'export du 2026-08-05, chargées en
4 secondes. La falaise de popularité est brutale — le premier décile couvre 406
à 3,71, les neuf autres se partagent 3,71 à 0.

*Reste ouvert* : `/tv/{id}/season/{n}?append_to_response=translations`
remplacerait-il les cinq appels par langue ? La réponse attendue est non — cet
endpoint ne porte que sur la saison, pas sur l'`overview` de chaque épisode —
mais elle n'a pas été vérifiée par une requête réelle, et le facteur est de
cinq sur le poste de coût dominant. Une seule requête suffit à trancher, avant
la passe complète.

### Lot 3 — Enrichissement externe

La table d'accueil existe déjà : `series_source` (§4). Reste à l'alimenter.

**Le raccordement, en trois entrées cumulées** — et non une chaîne, parce qu'une
chaîne casse au premier maillon :

1. `P4983` — l'identifiant TMDB porté directement par Wikidata. Aucun préalable ;
   63 154 séries l'ont.
2. `P345` — la chaîne actuelle, par l'`imdb_id` de `external_ids`. C'est elle qui
   couvre l'occidental, à 98 %.
3. Recherche par titre + année dans l'API de chaque Wikipédia, en dernier repli.

Chaque ligne écrite note dans `resolved_by` le chemin qui a réussi : le taux de
résolution par chemin devient une requête, plus une étude.

Puis Wikidata SPARQL → P915 (lieu de tournage) et P840 (lieu de l'action), et les
sitelinks → article Wikipédia **dans les cinq langues collectées**, en entier,
pas le résumé d'intro.

**TVmaze passe devant Wikidata comme porte d'entrée** — 40,0 % contre 38,7 % sur
un échantillon de 230 séries, et surtout par un autre chemin : la recherche par
titre y récupère 12,7 % de séries dont Wikidata ignore l'existence. Elle apporte
aussi ce que TMDB ne garantit pas — 99,2 % des épisodes datés, le calendrier, le
diffuseur. En revanche une série trouvée sur trois seulement a des résumés
d'épisode : c'est un raccordeur et une source de faits, pas de la matière de
notation. Détail dans
[`etude-sources-complementaires.md`](etude-sources-complementaires.md).

*Ce que le lot ne réparera pas.* Mesuré le 2026-08-06 : Wikidata ne connaît que
663 séries de langue arabe (plancher — `P364` est souvent absente) contre 4 898
`original_language=ar` chez TMDB. Aucune stratégie de jointure ne récupère ce qui
n'est pas écrit, et aucune des trois sources étudiées ne débloque ce corpus :
40 % de raccordement, 7,5 % de résumés d'épisode. Pour le catalogue arabe et
golfe, c'est une source dédiée ou rien — voir
[`etude-couverture-marche-arabe.md`](etude-couverture-marche-arabe.md).

*Et le fond de catalogue reste invisible.* Au dixième décile de popularité :
0 % d'item Wikidata, 6,7 % de série TVmaze. Au-delà du troisième décile,
l'enrichissement externe cesse d'être une stratégie — c'est une donnée d'entrée
pour le périmètre du lot 5.

*Livrable* : le **taux de raccrochage réel**, par corpus et par chemin. Combien
de séries sont raccordées et par quelle entrée, combien ont un lieu, combien ont
un article avec section intrigue. C'est ce chiffre qui décide si ces sources sont
des piliers ou des bonus.

### Lot 4 — Dérivation de la couche faits

`raw_source → series`, avec `id_tmdb` **unique et indexé** (la ligne était
commentée dans le ColumnSet V1 — premier correctif structurel), plus
`series_locations` et `series_people`. Modèles pydantic, dérivation pure, testée,
zéro appel réseau.

### Lot 5 — Rapport de couverture *(le vrai livrable)*

Par série et par décile de popularité : mots disponibles en overview seul /
+ synopsis d'épisodes / + Wikipédia ; complétude des faits ; couverture géo.

Plus le **constructeur de dossier de notation** — la fonction
`series_id → texte prêt à noter`, qui est l'interface exacte entre acquisition
et couche 2.

*Ce que le rapport tranche* : le périmètre, le budget de notation, et le rôle
de Wikipédia.

### Lot 6 — Passage à l'échelle *(partiellement livré)*

Déjà là, parce que le backfill ne pouvait pas s'en passer : `/tv/changes`
(`tmdb changes` marque les séries signalées, `backfill` les recollecte), le
parallélisme et la reprise sur incident.

Reste à faire, après lecture du rapport : les priorités de rafraîchissement
(haute : en production ou populaires, quotidien / moyenne : présentes dans des
fives, hebdomadaire / basse : fond de catalogue, mensuel). Le filtre qualité à
l'entrée, lui, est abandonné — voir §3.

## 6. Ce qui vient après l'acquisition

Noter un échantillon d'ancrage sur les 6 axes, mesurer les corrélations, trancher
*Exigence × Étrangeté*, et valider contre `similar_tmdb_raw` : deux séries que
TMDB juge similaires doivent être proches dans l'espace à 6 dimensions. C'est un
jeu d'évaluation gratuit, disponible sans annotation manuelle.

## 7. Références

| Fichier | Rôle |
|---|---|
| [`sourcing/README.md`](../sourcing/README.md) | installation et utilisation |
| [`sourcing/src/fiv_sourcing/sources/tmdb/client.py`](../sourcing/src/fiv_sourcing/sources/tmdb/client.py) | `append_to_response` — la décision non rejouable |
| [`sourcing/src/fiv_sourcing/sources/tmdb/export.py`](../sourcing/src/fiv_sourcing/sources/tmdb/export.py) | l'export quotidien → `tmdb_catalog` |
| [`sourcing/src/fiv_sourcing/sources/tmdb/backfill.py`](../sourcing/src/fiv_sourcing/sources/tmdb/backfill.py) | la collecte de masse, reprenable |
| [`sourcing/src/fiv_sourcing/sources/tmdb/changes.py`](../sourcing/src/fiv_sourcing/sources/tmdb/changes.py) | `/tv/changes` — ce qui a bougé chez TMDB |
| [`sourcing/migrations/001_sourcing.sql`](../sourcing/migrations/001_sourcing.sql) | le schéma de collecte |
| [`sourcing/migrations/002_tmdb_catalog.sql`](../sourcing/migrations/002_tmdb_catalog.sql) | l'inventaire du catalogue |
| [`sourcing/migrations/003_changes.sql`](../sourcing/migrations/003_changes.sql) | la marque de modification |
| [`sourcing/migrations/004_series_source.sql`](../sourcing/migrations/004_series_source.sql) | l'enrichissement externe, et `resolved_by` |
| `v2-sourcing-series.md` (dépôt V1) | l'analyse de l'existant et le modèle en trois couches |
