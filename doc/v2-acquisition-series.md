# Acquisition des données séries — plan de travail

> Suite opérationnelle de `v2-sourcing-series.md` (dépôt V1), qui décrit *quoi*
> collecter et pourquoi. Ce document-ci décrit *comment*, dans quel ordre, et ce
> qui a déjà été décidé.
>
> État : lot 1 livré. Lots 2 à 6 à faire.

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

**Le coût réel n'est pas TMDB, c'est la notation.** 17 requêtes HTTP par série
sur 250 000 séries, c'est quelques jours de machine et zéro euro. Six axes par
LLM sur 250 000 séries, c'est un budget. La sélection du périmètre est donc une
décision d'acquisition à part entière — la V1 n'avait aucun filtre qualité
sérieux (« pas adulte » et « au moins une affiche »).

**Le brut ne protège que de la dérivation.** Conserver le JSON permet de réviser
un axe ou d'ajouter une facette sans réseau. Mais ajouter un sous-appel à
`append_to_response` impose de retélécharger le catalogue entier. Corollaire :
cette liste se décide **une fois, largement, avant le grand run**. C'est la seule
décision non rejouable du projet.

## 3. Décisions prises

| Sujet | Décision |
|---|---|
| **Catalogue V1** | **Table rase.** On re-collecte tout depuis TMDB sur l'architecture cible. La V1 n'est plus une dépendance du chantier : ni son catalogue, ni son pipeline, ni son schéma. Le seul actif à ne pas perdre reste les fives utilisateurs (§5.3 du doc de sourcing), qui se raccorderont plus tard par `id_tmdb`. |
| **Périmètre** | Non décidé — **mesuré** au lot 5. L'échantillon stratifié donne la courbe « matière disponible × popularité » ; le seuil se lit dessus. |
| **Langage** | Python 3.12, **vendorisé** dans `sourcing/vendor/python`. Aucune dépendance à un Python système : le Makefile n'appelle jamais `uv run`, et un garde-fou échoue si la venv dérive. |
| **Exécution** | Deux cibles distinctes. **Poste de dev** : Python de `vendor/`, Postgres de la machine, pas de Docker. **Serveur** : tout conteneurisé, `Dockerfile` + `docker-compose.yml`. |
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
│    → append-only, jamais retouché, jamais interprété   │
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

### Lot 2 — Échantillon de 300 séries

Télécharger l'export quotidien `tv_series_ids_MM_DD_YYYY.json.gz`. Il contient
`id`, `original_name` **et `popularity`** pour tout le catalogue : c'est la base
de sondage, gratuite et sans une seule requête API. Stratifier en déciles de
log-popularité, 30 séries par décile, plus une liste d'ancrages tenue à la main
pour la calibration ultérieure des axes.

À mesurer ici : `/tv/{id}/season/{n}?append_to_response=translations`
remplacerait-il les deux appels fr/en ? Si oui, le coût saisons est divisé par
deux sur tout le catalogue. À valider sur 10 séries avant de figer.

### Lot 3 — Enrichissement externe

Wikidata SPARQL sur les `wikidata_id` → P915 (lieu de tournage) et P840 (lieu de
l'action). Puis sitelinks → article Wikipédia fr et en, en entier, pas le résumé
d'intro.

*Livrable* : le **taux de raccrochage réel**. Combien de séries ont un
`wikidata_id`, combien ont un lieu, combien ont un article fr avec section
intrigue. C'est ce chiffre qui décide si ces sources sont des piliers ou des
bonus.

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

### Lot 6 — Passage à l'échelle *(après lecture du rapport)*

`/tv/changes` + priorités de rafraîchissement (haute : en production ou
populaires, quotidien / moyenne : présentes dans des fives, hebdomadaire /
basse : fond de catalogue, mensuel), parallélisme, reprise sur incident, filtre
qualité à l'entrée.

## 6. Ce qui vient après l'acquisition

Noter les 300 sur les 6 axes, mesurer les corrélations, trancher
*Exigence × Étrangeté*, et valider contre `similar_tmdb_raw` : deux séries que
TMDB juge similaires doivent être proches dans l'espace à 6 dimensions. C'est un
jeu d'évaluation gratuit, disponible sans annotation manuelle.

## 7. Références

| Fichier | Rôle |
|---|---|
| [`sourcing/README.md`](../sourcing/README.md) | installation et utilisation |
| [`sourcing/src/fiv_sourcing/sources/tmdb/client.py`](../sourcing/src/fiv_sourcing/sources/tmdb/client.py) | `append_to_response` — la décision non rejouable |
| [`sourcing/migrations/001_sourcing.sql`](../sourcing/migrations/001_sourcing.sql) | le schéma de collecte |
| `v2-sourcing-series.md` (dépôt V1) | l'analyse de l'existant et le modèle en trois couches |
