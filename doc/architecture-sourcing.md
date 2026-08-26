# Architecture du sourcing — la cible

> Posée le 2026-08-06, après trois refontes dans la même journée — c'est
> précisément pour arrêter d'itérer dans le code que cette page existe. Elle
> décrit l'état **cible** ; l'écart avec l'existant et le chemin pour le
> résorber sont en §6.
>
> Statut : **validée sur le principe, à implémenter**. Rien ne se code qui la
> contredit ; si elle a tort, c'est elle qu'on corrige d'abord.

---

## 1. Les règles

**R1 — `raw_source` porte les références de base des séries, rien d'autre.**
Deux choses seulement : la collecte TMDB (fiches, saisons), et la **référence
Wikidata des séries hors TMDB** — la ligne par QID qu'écrit le crawler, qui
est la fiche d'identité de ces séries-là. **L'enrichissement n'écrit jamais
dans `raw_source`** : les réponses de Wikidata, Wikipédia et TVmaze obtenues
pour enrichir une série vont exclusivement dans `riche_source`, sous forme
interprétée. *(Décision du 2026-08-07, en connaissance du coût : changer un
jour l'extraction imposera de réinterroger les sources, ~37 h de réseau.)*

**R2 — Jamais le même contenu deux fois.**
Une seule entrée par objet dans `raw_source` (la déduplication par SHA-256 y
veille), et `riche_source` n'est **jamais une copie du brut** : c'est
l'*ajout* — le texte utile à la notation dans `content`, les faits canoniques
dans `facts`.

**R3 — TMDB est la première référence ; `oeuvre` est le pivot.**
On commence par parser les séries TMDB. `oeuvre` attache tout le reste : ses
identifiants externes sont nullables et uniques, ce qui permet d'accueillir une
série absente de TMDB et de la réconcilier si elle y apparaît un jour.
*Complément du 2026-08-21 :* l'univers **livres** n'a pas de TMDB
(doc/etude-sources-livres.md) — sa première référence est **Open Library**,
son flux principal est le crawler Wikidata (le « flux 2 » des séries), et le
pivot gagne un `id_openlibrary`. La règle ne change pas, seul le nom de la
première référence change avec l'univers.

**R4 — Rejouer l'enrichissement, c'est réinterroger.**
La dérivation TMDB (couche 1) se rejoue depuis `raw_source`, hors ligne, comme
toujours. L'enrichissement tiers, lui, n'a pas de brut (R1) : changer
l'extraction — sections d'article, fait supplémentaire — se paie d'une
réinterrogation des sources. Assumé le 2026-08-07 : ce sont des API gratuites
et stables, et `fetch_state` + `--refresh-after` savent cibler la reprise.

**R5 — Le JSON des données est uniforme partout.**
Un seul schéma de `facts`, quelles que soient la source et la série (§3). La
traduction des formats propriétaires vers ce schéma est concentrée dans **un
module unique**, `normalize.py` — la seule frontière entre les API extérieures
et le reste du projet. Un test garantit que chaque source produit exactement
ces clés.

## 2. Le schéma

```
schéma sourcing
│
│  ── LES RÉFÉRENCES DE BASE ───────────────────────────────
│  raw_source(source, kind, source_id, lang, payload, sha…)
│      la collecte TMDB (fiches, saisons)            ← R1
│      + la référence Wikidata des séries hors TMDB
│        (une ligne par QID, écrite par le crawler)
│      append-only, dédup par empreinte              ← R2
│      source_id = la clé de la série : id TMDB ou QID
│
│  fetch_state(source, kind, source_id, …)
│      l'état : quand on a regardé, quand ça a bougé
│
│  tmdb_catalog(id, original_name, popularity,
│               first_air_date, exported_on, changed_at)
│      l'inventaire TMDB, base de sondage
│
│  ── L'IDENTITÉ ───────────────────────────────────────────
│  oeuvre(id, univers, id_tmdb?, wikidata_qid?,      ← R3
│         imdb_id?, tvmaze_id?, titre?, annee?)
│      identifiants nullables, uniques par univers
│
│  ── LE DÉRIVÉ ────────────────────────────────────────────
│  riche_source(oeuvre_id, source, lang,             ← R4, R5
│               source_id, url, content, media,
│               facts, resolved_by, fetched_at)
│      une ligne par (œuvre, source, langue)
│      facts au schéma canonique, content allégé
```

La couche 1 (`catalog`, lot 4) **se raccrochera à `oeuvre_id`** : `oeuvre` est
l'identité, `catalog.series` n'en portera que les faits consolidés. Ça tranche
la question « deux tables d'identité » avant qu'elle ne se pose.

*Ménage inscrit à la cible* : `riche_source.id_tmdb` et
`riche_source.raw_source_id` sont redondants avec le pivot et se périment ;
ils disparaissent (§6, étape 5).

## 3. Le JSON canonique de `facts`

Mêmes clés pour toutes les sources ; une clé sans valeur est absente, jamais
inventée. Produit exclusivement par `normalize.py`.

```json
{
  "titre":               "Game of Thrones",
  "titres_alternatifs":  ["Le Trône de fer"],
  "annee":               2011,
  "statut":              "terminee",
  "pays":                ["US"],
  "langues":             ["en"],
  "lieux":               [{"type": "tournage", "nom": "Belfast"},
                          {"type": "action",   "nom": "Westeros"}],
  "diffuseur":           "HBO",
  "calendrier":          {"jours": ["Sunday"], "heure": "21:00"},
  "episodes":            {"total": 73, "dates": 73, "resumes": 73},
  "auteurs":             [{"qid": "Q5878", "nom": "Gabriel García Márquez"}],
  "editions":            {"par_langue": [{"langue": "fr", "nombre": 5,
                                          "isbn": "9782020238113", "annee": 1995}],
                          "total": 64, "sans_langue": 15, "tronque": false},
  "ids":                 {"tmdb": 1399, "imdb": "tt0944947",
                          "wikidata": "Q23572", "tvmaze": 82,
                          "openlibrary": "OL27258W"}
}
```

| Clé | Type | Qui la fournit |
|---|---|---|
| `titre`, `titres_alternatifs` | str, [str] | toutes |
| `annee` | int | TMDB, TVmaze, Wikidata |
| `statut` | `en_cours` \| `terminee` \| `annulee` | TMDB, TVmaze |
| `pays`, `langues` | [str] ISO | toutes |
| `lieux` | [{type, nom}] | Wikidata (P915/P840) |
| `diffuseur`, `calendrier` | str, {jours, heure} | TVmaze |
| `episodes` | {total, dates, resumes} | TVmaze, TMDB |
| `auteurs` | [{qid?, nom?}] | Wikidata (P50) — livres |
| `sitelinks` | int | Wikidata — livres, le proxy de popularité |
| `genres` | [{qid, nom}] | Wikidata (P136) — livres, libellés fr |
| `editions` | {par_langue, total, sans_langue, tronque} | Open Library — livres |
| `ids` | {tmdb?, imdb?, wikidata?, tvmaze?, openlibrary?} | toutes |

`content` (le texte de notation) et `media` (les visuels) restent des colonnes
à part : ce sont des matières, pas des faits.

## 4. Le texte Wikipédia : directement dans le dérivé

Décision du 2026-08-07, qui remplace « brut + dérivé allégé » de la veille :
l'article n'est **pas** conservé en brut. `riche_source.content` reçoit le
texte — à terme allégé aux seules sections narratives (étape 3), l'allègement
se faisant **au moment de la récupération**. Si la règle d'extraction change,
on réinterroge (R4).

## 5. Les deux flux d'entrée

**Flux 1 — TMDB d'abord** *(existant)* :

```
tmdb export → tmdb backfill → tmdb dates → enrich
   inventaire     le brut       dérivation    LIT raw_source (imdb_id)
                                              wikidata/wikipédia/tvmaze
                                                → riche_source, et rien d'autre
```

**Flux 2 — le crawler hors-TMDB** *(livré : `crawl wikidata`)* :

```
crawl wikidata
   1. balaye les items « série » de Wikidata SANS identifiant TMDB
      (SPARQL paginé ; mesuré : ~44 700 items, dont ~300 ar sans aucun id)
   2. crée l'oeuvre (id_tmdb null) et écrit LA RÉFÉRENCE DE BASE :
      le lookup par QID → raw_source (c'est la fiche d'identité
      de la série hors TMDB — l'équivalent de la fiche TMDB)
   3. enrichit : articles Wikipédia + TVmaze → riche_source
```

La **réconciliation** est portée par les index uniques d'`oeuvre` : si une
série du flux 2 apparaît un jour dans TMDB, l'enrichissement TMDB tentera de
revendiquer son QID, la collision sera journalisée « réconciliation à faire »,
et la fusion restera un geste humain — jamais un effet de bord silencieux.

## 6. De l'existant à la cible

L'existant (après `2f902de`) diffère sur trois points : le brut tiers n'est pas
conservé, les `facts` sont au format de chaque source, et `riche_source` traîne
deux références redondantes. Le chemin, en étapes indépendantes et petites :

| # | Étape | Nature |
|---|---|---|
| 1 | ✅ `normalize.py` + `facts` canoniques + test d'uniformité | livré |
| 2 | ✅ `enrich` n'écrit plus dans `raw_source` ; purge de l'enrichissement du brut (R1 du 2026-08-07) | livré |
| 3 | `content` allégé aux sections utiles, à la récupération (§4) | code |
| 4 | ✅ `crawl wikidata` — le flux 2, référence de base par QID | livré |
| 5 | retirer `riche_source.id_tmdb` et `raw_source_id` | migration de ménage |

L'ordre est le bon : 1 et 2 rendent le reste rejouable, 5 attend que tout le
monde lise le pivot. Aucune étape ne demande de re-télécharger quoi que ce
soit ; la passe d'enrichissement complète (~37 h) gagne à attendre l'étape 2,
pour que le brut tiers soit conservé dès la première fois.

## 7. Ce qui ne change pas

La collecte TMDB (backfill, dates, changes), `fetch_state` comme unique état de
reprise, `tmdb_catalog` comme inventaire, le protocole d'appariement TVmaze
(le titre cherche, l'`imdb_id` décide), les débits par hôte, les garde-fous
(migrations en attente, arrêt propre), et l'invariant fondateur : une réponse
HTTP = une ligne de brut, jamais retouchée, jamais interprétée.
