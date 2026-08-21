# L'actualité des œuvres : architecture

Rédigée le 2026-08-18, après ré-analyse du dépôt. Remplace la note de travail
« flux d'actualité (news + RSS) » — même intention, mais recadrée sur ce que le
projet veut **maintenant** : un mécanisme régulier qui accroche des événements
datés aux œuvres du pivot. Pas de salons, pas d'assistant — de l'acquisition.
Les consommateurs (fiche admin, et plus tard le front) lisent une table, ils
n'imposent rien à la collecte.

## 0. Ce que la ré-analyse a établi

Cinq faits du dépôt commandent l'architecture, et deux corrigent la note
d'origine :

1. **L'univers livre s'appelle `livres`, pas `books`.** C'est la clé de
   `oeuvre.univers` et de `univers.py` (`LIVRES`, migration 015). Sa « fiche »
   est un lookup Wikidata (`kind = lookup_book`), pas une fiche TMDB — il n'a
   donc pas de diffs TMDB, et son actualité viendra du RSS d'abord.
2. **`raw_source` ne grandit que quand le contenu change.** `store_raw`
   déduplique par empreinte : une recollecte identique n'écrit rien. Toute
   nouvelle ligne de fiche EST donc un changement réel — le diff
   « dernière fiche contre précédente » est incrémental par construction, et
   il est **gratuit**.
3. **La périodicité existe déjà** : `scripts/nightly.sh` (cron 10h30, flock,
   journaux datés) enchaîne export → changes → backfill → enrich → refresh →
   sync. L'actualité s'y insère ; elle n'invente pas de planificateur.
4. **Le client HTTP ne sait pas faire de GET conditionnel** (`etag` /
   `If-Modified-Since`) ni rendre du texte brut — deux ajouts nécessaires pour
   le RSS, et pour lui seul.
5. **La fiche admin a déjà son patron de consommation** :
   `/catalog/works/{id}/…` avec `media` qui qualifie l'identifiant. L'onglet
   actualité suivra ce patron, pas un nouveau.

## 1. Le flux, en une image

```
                    ┌─ COLLECTE (append-only, jamais interprétée) ─┐
  TMDB (existant) ──► raw_source ──┐
  RSS  (nouveau)  ──► raw_rss_item ┤                     curseur / etag
                                   │
                    ┌─ DÉRIVATION (rejouable, hors ligne) ────────┐
                                   │
             diffs de fiches ──────┼──► actualite (liaison certaine)
             liaison + typage ─────┴──► actualite (liaison scorée)
                                   │        ▲
                        cache de typage ────┘   (l'étape payée ne se repaie pas)
                                   │
                    ┌─ CONSOMMATION ──────────────────────────────┐
                        fiche admin · surveillance · (front, plus tard)
```

Deux invariants du dépôt sont conservés tels quels : `raw_source` reste
exclusivement TMDB (le RSS a sa table brute à lui), et rien ne se collecte et
ne s'interprète dans le même geste — le modèle est `changes.py`, marquer
d'abord, dériver ensuite.

## 2. Le schéma — migration sourcing `016_actualite.sql`

Cinq tables, chacune avec une raison d'exister séparément :

**`rss_feed`** — le registre des flux. En base et pas dans le code : ajouter
un flux est une ligne SQL ou un geste admin, pas un déploiement. Porte l'état
de collecte (`etag`, `last_modified`, `last_status`, `last_success_at`) parce
que `fetch_state` n'a pas ces colonnes et n'a pas à les gagner pour un seul
usage. `univers text[]` en indice de liaison (« ce flux parle de livres »).

**`raw_rss_item`** — le brut RSS, append-only, pendant de `raw_source`.
`unique (feed_id, guid, digest)` : un item ré-émis à l'identique n'écrit rien,
un item corrigé par l'éditeur écrit une nouvelle ligne. Le payload est
**normalisé en liste blanche** : `title`, `link`, `guid`, `published`, `tags`,
et `summary` tronqué à 500 caractères à la phrase. Tout le reste est jeté à
l'entrée — `content:encoded` en tête, car certains éditeurs y expédient
l'article entier et la frontière juridique du projet est précisément de ne
jamais le stocker. Écarter à l'entrée plutôt qu'à l'affichage : ce qui n'est
pas en base ne peut pas fuir.

**`actualite`** — la dérivation. Les colonnes qui portent les décisions :

```sql
oeuvre_id      bigint references sourcing.oeuvre(id),   -- null = non liée
type_evenement text not null check (type_evenement in (
    'saison_annoncee', 'date_diffusion', 'diffusion_terminee', 'annulation',
    'sortie', 'parution', 'critique', 'adaptation', 'prix', 'deces', 'autre')),
survenu_le     date not null,
titre          text not null,
url            text,                  -- null pour les diffs internes
editeur        text not null,         -- 'tmdb' | 'telerama' | …
raw_source_id  bigint references sourcing.raw_source(id),
raw_rss_item_id bigint references sourcing.raw_rss_item(id),
confiance_liaison real,               -- null = liaison certaine (diff interne)
```

Le `check` est la fermeture du vocabulaire — c'est un LLM qui écrira cette
colonne pour le RSS, et une valeur inventée doit être une erreur bruyante au
moment où elle se produit, pas une catégorie fantôme découverte des mois plus
tard. Deux clés naturelles partielles empêchent le rejeu de dupliquer :
`unique (raw_source_id, type_evenement)` et
`unique (raw_rss_item_id, type_evenement)` — `oeuvre_id` hors des clés, pour
qu'une liaison corrigée mette à jour au lieu de doubler.

**`actualite_typage`** — le cache de l'étape payée :
`(digest de l'item, sha du prompt) → type + date extraite`. La dérivation est
rejouable, mais son typage passe par Haiku : sans ce cache, chaque rejeu
repaierait un travail identique, et le mode d'itération annoncé (corriger,
rejouer) se découragerait de lui-même. La règle qu'il matérialise : **on paie
quand ce qu'on a changé est ce qui coûte.** Changer le code de liaison ne
repaie rien ; changer le prompt repaie, et c'est légitime.

**`actualite_curseur`** — le point de reprise des diffs : une ligne par
`kind`, le dernier `raw_source.id` traité. `raw_source` est append-only à ids
croissants ; un high-water mark suffit, et il est honnête — pas de scan.

## 3. Les dérivations

### D1 — les diffs de fiches (gratuit, liaison certaine)

Pour chaque nouvelle ligne de fiche au-delà du curseur, comparer au payload
précédent de la même œuvre :

| observation | événement |
|---|---|
| une saison apparaît dans `seasons` | `saison_annoncee` |
| `next_episode_to_air` gagne ou change de date | `date_diffusion` |
| `status` → `Ended` / `Canceled` | `diffusion_terminee` / `annulation` |
| `release_date` posée ou changée (films) | `sortie` |
| `status` film → `Released` | `sortie` |

`editeur = 'tmdb'`, `confiance_liaison = null` : c'est notre pivot, la
liaison est un fait. Les livres n'ont rien ici en v1 ; leur lookup Wikidata
permettra plus tard de détecter un prix (P166 qui s'allonge → `prix`), noté
comme extension, pas construit.

### D2 — liaison et typage RSS (scoré, plafonné par un seuil)

Par item brut non dérivé : extraire les titres candidats du titre et du
résumé, matcher contre le pivot — `oeuvre.titre`, `tmdb_catalog`, et les
titres multilingues de `riche_source` (sitelinks Wikidata). Signaux de
désambiguïsation : année, mots-clés (« saison », « tome »), noms de personnes
présents dans l'item ET dans les faits de l'œuvre. Trois issues : lié, lié
mais marqué pour revue, non lié. **Les homonymes sont le cas dimensionnant :
dans le doute entre deux œuvres, on ne lie pas** — un item non lié est de
l'actualité générale, un item mal lié empoisonne tout ce qui lira la table.

Le typage passe par le cache avant Haiku. Le vocabulaire et le prompt vivent
dans le module, versionnés ; le `check` SQL les garde honnêtes.

## 4. La périodicité — deux rythmes, pas un

**Quotidien, dans `nightly.sh`** : la dérivation D1, insérée après
`backfill` — c'est lui qui fait grossir `raw_source`, donc c'est sa fin qui
rend les diffs disponibles. En `|| true`, comme les sync : rien en aval ne
doit faire échouer une collecte.

**Horaire, script séparé (`scripts/actualite.sh`)** : `rss-sweep` puis
`actualite-derive`, flock, journaux datés — le patron de `nightly.sh` en plus
petit. Horaire et pas plus : les GET conditionnels font que la plupart des
passages coûtent des 304, et l'actualité culturelle ne bouge pas à la minute.

## 5. L'ordre de construction — la valeur d'abord

1. **Migration + D1 + l'onglet fiche.** Trois briques, zéro réseau nouveau,
   zéro liaison à valider — et le résultat est exactement la demande
   d'origine : « les news de TMDB quand on affiche un élément ».
   `/catalog/works/{id}/actualite?media=…`, panneau dans la fiche admin.
2. **La surveillance** : état des flux, items récents, file de revue des
   liaisons en zone grise. Construite AVANT que la liaison RSS soit déclarée
   finie, parce que c'est elle qui fabrique l'échantillon des 100 items à
   vérifier — la leçon payée trois fois dans ce projet : compter avant de
   croire.
3. **HTTP conditionnel + `rss-sweep`** avec le registre initial (Télérama,
   Allociné, Première, ActuaLitté, Livres Hebdo, Variety, THR — URLs à
   vérifier une à une au moment de l'implémentation, elles périment).
4. **D2 liaison + typage**, cache compris, mesurée dans la surveillance :
   ≥ 95 liaisons correctes sur 100, homonymes non liés plutôt que mal liés.
5. **Le cron horaire**, en dernier — on n'automatise que ce qu'on a vu juste.

## 6. Ce qui est volontairement dehors

Le fetch des pages d'articles (frontière juridique, définitive) ; les salons
et l'assistant (consommateurs futurs de la table, chantiers séparés) ; les
diffs Open Library (le dump n'est pas encore la base de sondage) ; tout
affichage front — l'admin d'abord, le temps de mesurer la qualité de liaison.
