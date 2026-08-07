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

**R1 — `raw_source` porte le brut de TMDB et de Wikidata/Wikimedia.**
Append-only, dédupliqué par empreinte, une ligne par réponse. Jamais TVmaze :
TVmaze est un enrichissement pur (raccordeur + faits, mesuré : peu de texte),
il entre directement en dérivé.

**R2 — Jamais le même contenu deux fois.**
Une seule entrée par objet dans `raw_source` (la déduplication par SHA-256 y
veille), et `riche_source` n'est **jamais une copie du brut** : c'est une
*interprétation* — extraite, normalisée, allégée. Le cas concret : l'article
Wikipédia complet vit dans le brut ; `riche_source.content` n'en garde que
l'extrait utile à la notation (§4).

**R3 — TMDB est la première référence ; `oeuvre` est le pivot.**
On commence par parser les séries TMDB. `oeuvre` attache tout le reste : ses
identifiants externes sont nullables et uniques, ce qui permet d'accueillir une
série absente de TMDB et de la réconcilier si elle y apparaît un jour.

**R4 — `riche_source` est rejouable.**
Pour Wikidata et Wikipédia, la dérivation se rejoue depuis `raw_source`, hors
ligne. Pour TVmaze — pas de brut, R1 — rejouer signifie réinterroger l'API :
assumé, c'est une API gratuite, stable et rapide.

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
│  ── LE BRUT ──────────────────────────────────────────────
│  raw_source(source, kind, source_id, lang, payload, sha…)
│      source ∈ { tmdb, wikidata, wikipedia }        ← R1
│      append-only, dédup par empreinte              ← R2
│      source_id = LA CLÉ DE LA SÉRIE, partout :
│        id TMDB (flux 1) ou QID (flux 2) — jamais
│        un titre ; le titre vit dans le payload
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
  "ids":                 {"tmdb": 1399, "imdb": "tt0944947",
                          "wikidata": "Q23572", "tvmaze": 82}
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
| `ids` | {tmdb?, imdb?, wikidata?, tvmaze?} | toutes |

`content` (le texte de notation) et `media` (les visuels) restent des colonnes
à part : ce sont des matières, pas des faits.

## 4. Le texte Wikipédia : brut complet, dérivé allégé

Décision du 2026-08-06 (« brut + dérivé allégé ») :

- **`raw_source`** garde la réponse complète de l'API — l'article entier.
  C'est ce qui rend l'extraction rejouable ;
- **`riche_source.content`** ne garde que **l'extrait utile à la notation** :
  les sections narratives (intrigue, synopsis, épisodes), sans l'infobox, les
  références, les listes de distribution ni les liens externes. L'extraction
  des sections est une dérivation comme une autre — si elle change, on rejoue
  depuis le brut, zéro réseau.

## 5. Les deux flux d'entrée

**Flux 1 — TMDB d'abord** *(existant)* :

```
tmdb export → tmdb backfill → tmdb dates → enrich
   inventaire     le brut       dérivation    wikidata/wikipédia → raw_source
                                              normalisation      → riche_source
                                              tvmaze             → riche_source
```

**Flux 2 — le crawler hors-TMDB** *(livré : `crawl wikidata`)* :

```
crawl wikidata
   1. balaye les items « série » de Wikidata SANS identifiant TMDB
      (SPARQL paginé ; mesuré : ~44 700 items, dont ~300 ar sans aucun id)
   2. crée l'oeuvre (id_tmdb null) et le brut par QID :
      lookup + entity + articles → raw_source
   3. enrichit : TVmaze (par P8600 ou imdb_id) → riche_source
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
| 2 | ✅ `enrich` réécrit le brut wikidata/wikipédia dans `raw_source` (R1) | livré |
| 3 | `content` allégé aux sections utiles (§4) | dérivation, rejouable |
| 4 | ✅ `crawl wikidata` — le flux 2 | livré |
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
