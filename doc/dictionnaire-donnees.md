# Dictionnaire des données — le schéma `sourcing`, table par table

> La référence détaillée de la donnée : chaque table, chaque colonne, la
> structure des payloads, le cycle de vie d'une série, les volumes mesurés.
>
> Les documents frères : [`architecture-sourcing.md`](architecture-sourcing.md)
> pour les *règles* (pourquoi c'est comme ça),
> [`contrat-donnees-admin.md`](contrat-donnees-admin.md) pour la *lecture* côté
> admin (les langues notamment), [`exploitation.md`](exploitation.md) pour le
> *faire tourner*. Rédigé le 2026-08-07.

---

## 1. Vue d'ensemble

Une base — `fivorites_v2` — un schéma par domaine. `sourcing` porte cinq
tables, organisées en trois étages :

```
 LES RÉFÉRENCES DE BASE          L'IDENTITÉ            LE DÉRIVÉ
┌─────────────────────┐      ┌──────────────┐      ┌──────────────────┐
│ tmdb_catalog        │      │              │      │                  │
│  l'inventaire TMDB  │      │    oeuvre    │◄─────│   riche_source   │
├─────────────────────┤      │   le pivot   │      │ l'enrichissement │
│ raw_source          │◄─────│              │      │                  │
│  le brut, jamais    │      └──────────────┘      └──────────────────┘
│  interprété         │
├─────────────────────┤      public.schema_migrations : l'historique
│ fetch_state         │      des migrations, pour la base entière
│  l'état de reprise  │
└─────────────────────┘
```

Deux flux alimentent le tout :

- **Flux 1 (TMDB d'abord)** : `export` remplit l'inventaire → `backfill`
  collecte le brut → `dates` dérive → `enrich` ajoute Wikidata, Wikipédia et
  TVmaze dans `riche_source` ;
- **Flux 2 (hors TMDB)** : `crawl wikidata` crée l'œuvre par QID, pose sa
  référence de base dans le brut, et l'enrichit pareil.

---

## 2. `tmdb_catalog` — l'inventaire

Une ligne par œuvre **connue de TMDB** — 228 953 séries et 1 231 681 films au
2026-08-12, alimentée par l'export public quotidien
(`tv_series_ids_MM_DD_YYYY.json.gz` — aucune clé, aucun quota). Ce n'est pas du
brut : c'est la liste de ce qui existe, la base de sondage, et le point de
départ de toute collecte. ~229 000 lignes de séries au 2026-08-12.

La clé primaire est `(univers, id)` depuis le lot 12, et ce n'est pas de la
prudence : sans elle, le premier `on conflict (id) do update` d'un export de
films remplacerait les séries qui portent les mêmes numéros — sans erreur, et
sans retour en arrière.

| Colonne | Type | Signification |
|---|---|---|
| `univers` | text, **PK** | `series` \| `movies`. ⚠️ Ajouté au lot 12 : les identifiants TMDB de films et de séries se chevauchent, `1399` désigne *Game of Thrones* **et** un film |
| `id` | integer, **PK** | l'id TMDB — unique **dans son univers**, jamais seul |
| `original_name` | text | le titre original (dans l'alphabet d'origine) |
| `popularity` | real | la métrique d'usage du *site* TMDB. ⚠️ jamais un filtre : biais occidental mesuré (facteur 6 contre l'écriture arabe) |
| `adult` | boolean | le drapeau TMDB |
| `exported_on` | date | dernier export où l'id a été vu. **Une date qui décroche = série disparue de TMDB** |
| `first_seen_at` | timestamptz | premier export qui a vu l'id → détection des **nouveautés** |
| `last_seen_at` | timestamptz | dernier passage de l'export |
| `changed_at` | timestamptz | posé par `tmdb changes` (`/tv/changes`) : TMDB signale une modification → `backfill` recollectera |
| `first_air_date` | date | **dérivée** du brut par `tmdb dates` (la date vit dans le payload de la fiche ; trier 228 000 séries sur un `jsonb` décompresserait la table). Null = pas encore collectée |

Index : `popularity desc` (échantillonnage), `exported_on` (disparues),
`changed_at` partiel (le rattrapage), `(first_air_date desc nulls last,
popularity desc)` (le tri `recent`).

---

## 3. `raw_source` — le brut

**Append-only, jamais retouché, jamais interprété.** Une ligne par réponse
HTTP conservée. Ne porte que les **références de base** (R1) : la collecte
TMDB, et la référence Wikidata des séries hors TMDB. L'enrichissement n'y
écrit jamais.

| Colonne | Type | Signification |
|---|---|---|
| `id` | bigserial, **PK** | — |
| `source` | text | `tmdb`, ou `wikidata` (flux 2 uniquement) |
| `kind` | text | voir le tableau des kinds ci-dessous |
| `source_id` | text | **la clé de la série** : id TMDB (`'1399'`, `'1399/s2'` pour une saison) ou QID (`'Q777'`). Jamais un titre |
| `lang` | text, null | la langue de la *requête* (voir [`contrat-donnees-admin.md`](contrat-donnees-admin.md) §2 — piège classique) |
| `fetched_at` | timestamptz | quand la réponse a été obtenue |
| `http_status` | integer | **un 404 est un résultat** (série supprimée de TMDB), pas une erreur. Les 401/403 ne sont jamais stockés : ils parlent de notre configuration, pas de l'œuvre |
| `payload` | jsonb | la réponse telle quelle (null si échec) |
| `payload_sha256` | bytea | l'empreinte du payload canonicalisé — la déduplication : rejouer une collecte inchangée n'écrit rien |

Les kinds :

| `source` / `kind` | Contenu | Lignes par série |
|---|---|---|
| `tmdb` / `tv` | la fiche complète (§3.1) | 1 (× l'historique des re-collectes) |
| `tmdb` / `tv_season` | une saison, épisodes compris (§3.2) | nb saisons × 5 langues |
| `wikidata` / `lookup` | la référence de base d'une série **hors TMDB** (flux 2) | 1 |

### 3.1 Le payload d'une fiche (`tv`)

La fiche est demandée avec un `append_to_response` large — **la seule décision
non rejouable du projet** : ajouter un sous-appel plus tard imposerait de tout
retélécharger. Ce qu'elle contient :

| Bloc | Champs utiles |
|---|---|
| racine | `id`, `name`, `original_name`, `overview` (version fr-FR), `first_air_date`, `last_air_date`, `status`, `genres[]`, `origin_country[]`, `original_language`, `popularity`, `vote_average`, `vote_count`, `number_of_seasons`, `seasons[]` (la liste qui pilote la collecte des saisons) |
| `external_ids` | `imdb_id`, `wikidata_id`, `tvdb_id`… — **les clés de jointure**, sans lesquelles aucun raccordement |
| `translations.translations[]` | ~45 entrées `{iso_639_1, iso_3166_1, data:{name, overview, tagline}}` — les synopsis de série de toutes les langues, dans cette seule ligne |
| `images` | `posters[]`, `backdrops[]`, `logos[]` (chemins vers image.tmdb.org) |
| `aggregate_credits` | distribution consolidée sur toute la série (là où `credits` ne voit que la saison 1) |
| `content_ratings` | classifications par pays |
| `watch/providers` | plateformes de streaming **par pays** (donnée JustWatch, attribution obligatoire) |
| `keywords`, `alternative_titles`, `recommendations`, `similar`, `videos`, `episode_groups`, `reviews`, `credits` | le reste de l'append |

### 3.2 Le payload d'une saison (`tv_season`)

`{season_number, name, overview, air_date, episodes[]}` + `credits`,
`external_ids`, `images`, `videos`. Chaque épisode :
`{episode_number, name, overview, air_date, runtime, still_path, …}` — et
l'`overview` est **dans la langue de la ligne** (`lang`) : c'est toute la
raison des cinq lignes par saison, vérifiée par requête réelle le 2026-08-07
(l'endpoint `translations` d'une saison ne couvre pas les épisodes).

### 3.3 Le payload d'un lookup Wikidata (flux 2)

La réponse SPARQL du lookup par QID : `results.bindings[0]` avec `item`,
`imdb`, `tvmaze`, et les agrégats `pays`, `langues`, `tournage`, `action`
(valeurs jointes par `|`, **triées** — Blazegraph ne garantit pas l'ordre des
`GROUP_CONCAT`, et sans tri chaque rejeu créerait une ligne pour un contenu
identique).

---

## 4. `fetch_state` — l'état de reprise

Une ligne par objet regardé — succès **ou échec**. C'est elle qui rend tout
reprenable : `backfill`, `enrich` et `crawl` recalculent leur liste dessus à
chaque lancement. Remplace les trois fichiers JSON sur disque de la V1.

| Colonne | Signification |
|---|---|
| `source`, `kind`, `source_id` | **PK** — même adressage que `raw_source` |
| `priority` | 1 haute / 2 moyenne / 3 fond de catalogue (les cadences du lot 6, pas encore exploitées) |
| `last_fetched_at` | quand on a **regardé** — distinct de… |
| `last_changed_at` | …quand ça a **bougé** (contenu réellement nouveau) |
| `last_success_at` | dernier passage réussi — le critère « collectée » |
| `attempts`, `last_status`, `last_error` | le diagnostic |

Les kinds vivants : `tmdb/tv`, `tmdb/tv_season`, `wikidata/lookup` (id TMDB au
flux 1, QID au flux 2 — c'est ce dernier qui porte la reprise de tout
l'enrichissement d'une série).

---

## 5. `oeuvre` — le pivot d'identité

Aucun identifiant universel n'existe dehors (la moitié du Wikidata « séries »
ignore TMDB ; TVmaze ne porte jamais d'id TMDB) : **le nôtre est `oeuvre.id`**.
C'est l'`oeuvre_id` que la couche 2 (notation) attendait — elle l'utilise
depuis le lot 12 — et l'identité à laquelle la couche 1 (`catalog.series`,
lot 4) se raccrochera.

Toute la notation s'y range désormais : `notation.score`, `training_run`,
`media_caption`, `embedding`, plus `sourcing.video` et `video_scan`. Une note
ne dit plus « la série TMDB 1399 vaut 8 en action » mais « l'œuvre 4212 vaut 8
en action » — et c'est le pivot qui sait de quelle œuvre il s'agit, dans quel
univers, chez quelles sources.

| Colonne | Signification |
|---|---|
| `id` | bigserial, **PK** — l'identifiant d'œuvre du projet |
| `univers` | `series` aujourd'hui ; `movies`, `books`, `bd`, `musics` demain |
| `id_tmdb` | nullable, unique par univers — **null = série hors TMDB** |
| `wikidata_qid`, `imdb_id`, `tvmaze_id` | nullables ; qid et tvmaze uniques par univers |
| `titre`, `annee` | pour les œuvres hors TMDB c'est tout ce qu'on a ; sinon confort de lecture |
| `created_at` | — |

Créée **à la collecte** depuis le lot 12 : une œuvre existe dès que sa fiche a
été téléchargée. Elle naissait auparavant à l'enrichissement, ce qui suffisait
tant que le pivot ne servait qu'à `riche_source` ; ça ne suffit plus depuis que
la notation s'y range — une série collectée doit pouvoir être notée sans avoir
été enrichie, et l'administration n'écrit jamais dans `sourcing`.

Conséquence sur la lecture : **la présence du pivot ne dit plus « enrichie »**.
Ce sont ses identifiants externes qui le disent, eux seuls ne pouvant venir que
de Wikidata, d'IMDb ou de TVmaze.

⚠️ Aucune clé étrangère vers `tmdb_catalog`, et c'est délibéré : l'inventaire
est une base de sondage remplie une fois par jour, une série créée aujourd'hui
apparaît dans `/tv/changes` — donc peut être collectée — avant d'entrer dans
l'export de demain. Faire dépendre l'identité de l'inventaire ferait échouer
`tmdb fetch --id` sur une nouveauté parfaitement réelle.

Les identifiants appris en route remontent par `coalesce` — on complète, on
n'écrase pas — et une collision d'unicité est journalisée « **réconciliation à
faire** » : la fusion de deux identités est un geste humain, jamais un effet de
bord.

---

## 6. `riche_source` — l'enrichissement

**L'ajout** : ce que les sources tierces apportent, une ligne par (œuvre,
source, langue), remplacée à chaque passe (l'état courant ; l'historique n'est
pas son travail). Jamais une copie de brut : du texte utile et des faits
canoniques.

| Colonne | Signification |
|---|---|
| `id` | bigserial, **PK** |
| `oeuvre_id` | → `oeuvre`, **la** clé d'attache ; unique avec (source, lang) |
| `id_tmdb`, `raw_source_id` | nullables (null = œuvre hors TMDB). ⚠️ redondants avec le pivot, leur retrait est l'étape 5 de l'architecture |
| `source` | `wikidata`, `wikipedia`, `tvmaze` |
| `lang` | l'édition linguistique (`''` si la source est monolingue) |
| `source_id` | l'objet chez la source : `'Q23572'`, le titre d'article, l'id TVmaze |
| `url` | la page qui fait autorité, pour vérifier à la main |
| `content` | **le texte de notation** — l'article Wikipédia, les résumés d'épisode TVmaze concaténés |
| `media` | `[{type, url}]` — l'affiche TVmaze par ex. |
| `facts` | **le JSON canonique** (§6.1) — le seul lieu de vie des faits tiers |
| `resolved_by` | le chemin du raccordement : `p4983`, `p345`, `p8600`, `imdb`, `title`, `sitelink`, `sweep`. Rend le taux de résolution mesurable par un `group by` |
| `fetched_at` | — |
| `content_chars`, `media_count` | **calculées** — seuiller (« ≥ 2 000 caractères ») sans décompresser le texte |

### 6.1 Le JSON canonique de `facts`

Mêmes clés quelle que soit la source, produites exclusivement par
`normalize.py`. Une clé sans valeur est **absente**, jamais inventée.

```json
{
  "titre": "Game of Thrones",       "titres_alternatifs": ["…"],
  "annee": 2011,                    "statut": "terminee",
  "pays": ["US"],                   "langues": ["en"],
  "lieux": [{"type": "tournage", "nom": "Belfast"},
            {"type": "action",   "nom": "Westeros"}],
  "diffuseur": "HBO",               "calendrier": {"jours": ["Sunday"], "heure": "21:00"},
  "episodes": {"total": 73, "dates": 73, "resumes": 73},
  "ids": {"tmdb": 1399, "imdb": "tt0944947", "wikidata": "Q23572", "tvmaze": 82}
}
```

### 6.2 Ce que chaque source dépose

| Source | `content` | `facts` typiques | `media` |
|---|---|---|---|
| `wikidata` | — (les faits, pas du texte) | `pays`, `langues`, `lieux`, `ids` | — |
| `wikipedia` (× langue) | l'article en texte brut, marqueurs `== Section ==` inclus | — | — |
| `tvmaze` | les résumés d'épisode concaténés (1 série trouvée sur 3 en a) | `titre`, `annee`, `statut`, `diffuseur`, `calendrier`, `episodes`, `ids` | l'affiche |

---

## 7. Le cycle de vie d'une série

```
export quotidien ──► tmdb_catalog (first_seen_at)          « elle existe »
        backfill ──► raw_source tv + tv_season×5           « collectée »
                     fetch_state tmdb/tv (last_success_at)
      tmdb dates ──► tmdb_catalog.first_air_date           « datée »
        backfill ──► oeuvre (le pivot naît ici, lot 12)    « identifiée »
                     riche_source wikidata/wikipedia×n/tvmaze  « enrichie »
                     fetch_state wikidata/lookup           « ne sera pas retentée »
 catalog refresh ──► admin.tv_card                         « visible dans l'admin »
   /tv/changes   ──► tmdb_catalog.changed_at → backfill recollectera
   export absent ──► exported_on décroche                  « disparue de TMDB »
```

Le cas hors TMDB entre par `crawl wikidata` : œuvre par QID (`id_tmdb` null),
référence de base dans le brut, puis même enrichissement.

## 8. Ordres de grandeur mesurés

| | |
|---|---|
| Catalogue | 228 454 séries (export du 2026-08-05) |
| Collecte | ~10 requêtes/série en moyenne (1 fiche + saisons × 5 langues) ; ~2,2 M de requêtes, ~30 h à 20 req/s, zéro 429 observé |
| Raccordement Wikidata | ~36 % des séries ont un item (73 % au 1er décile de popularité, 0 % au 10e) |
| Enrichissement | 1,17 requête/série (résolutions par lots de 100), ~37 h pour le catalogue |
| Matière d'une série bien dotée | *Game of Thrones* : ~258 000 caractères (5 articles + résumés TVmaze) contre 400 pour l'overview TMDB |
| Hors TMDB (noyau dur) | ~44 700 items Wikidata sans id TMDB, dont 300 de langue arabe sans aucun identifiant |
