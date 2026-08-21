# Le contrat de données du sourcing, vu de l'admin

> Ce document s'adresse à qui développe `admin/` — il explique comment lire les
> tables du schéma `sourcing`, et en particulier **pourquoi les langues n'ont
> pas la même forme selon le type de ligne**. Ouvrir un thread avec ce seul
> fichier doit suffire pour travailler côté admin sans relire le sourcing.
>
> Rédigé le 2026-08-07. Les règles de fond vivent dans
> [`architecture-sourcing.md`](architecture-sourcing.md) ; le détail colonne par
> colonne dans [`dictionnaire-donnees.md`](dictionnaire-donnees.md).

---

## 0. « Où est la version anglaise / espagnole ? » — le raccourci

| Vous cherchez | C'est ici |
|---|---|
| titre + synopsis **de la série** en langue X | la fiche unique (`kind='tv'`) → `payload -> 'translations' -> 'translations'`, filtrer `iso_639_1` (et `iso_3166_1` : il peut y avoir en/US *et* en/GB) |
| synopsis **des épisodes** en langue X | la ligne saison de cette langue : `kind='tv_season'`, `lang='en-US'` / `'es-ES'` — et nulle part ailleurs |
| **l'article Wikipédia** en langue X | `riche_source` : `source='wikipedia'`, `lang='en'` / `'es'` |

## 1. Le contrat des langues, en une phrase

**Toutes les séries sont importées dans cinq langues — fr, en, es, ar, tr —
mais TMDB ne livre pas les fiches et les saisons de la même façon.** C'est
l'asymétrie qu'on voit dans `raw_source`, et elle est normale.

## 2. La colonne `lang` : la langue de la *requête*, pas du contenu

| `kind` | Lignes par objet | Ce que `lang` veut dire |
|---|---|---|
| `tv` (la fiche) | **1 seule**, `lang = 'fr-FR'` | la langue demandée à TMDB — mais le payload contient **toutes les langues** (voir §3) |
| `tv_season` | **5**, une par langue | la langue du contenu : les synopsis d'épisode de cette ligne sont dans cette langue-là |

Ne jamais déduire « cette série n'existe qu'en français » du `fr-FR` d'une
fiche : c'est un artefact de requête.

## 3. La fiche (`kind='tv'`) : une ligne, toutes les langues

TMDB permet d'embarquer `translations` dans l'appel de la fiche : une seule
requête rapporte les synopsis de série de ~45 langues. D'où une seule ligne.

Pour lire le synopsis de série en langue X :

```sql
select t ->> 'iso_639_1' as langue,
       t -> 'data' ->> 'name'     as titre,
       t -> 'data' ->> 'overview' as synopsis
from sourcing.raw_source,
     jsonb_array_elements(payload -> 'translations' -> 'translations') t
where source = 'tmdb' and kind = 'tv' and source_id = '1399'
  and t ->> 'iso_639_1' = 'ar';
```

Le champ `payload ->> 'overview'` à la racine est la version `fr-FR` (langue de
la requête) ; les autres langues sont dans `translations`.

## 4. Les saisons (`kind='tv_season'`) : une ligne par langue, et c'est le seul endroit où vivent les synopsis d'épisode traduits

Il n'existe **aucun raccourci** côté TMDB pour les épisodes — vérifié par
requête réelle le 2026-08-07 : l'endpoint `translations` d'une saison ne couvre
que le nom et le synopsis *de la saison*, jamais les épisodes. Le seul moyen
d'avoir l'épisode 3 en arabe est de demander toute la saison avec
`language=ar-SA`.

Conséquences pour l'admin :

- les synopsis d'épisode en langue X sont dans la ligne
  `(tv_season, '1399/s1', lang='X')` — et nulle part ailleurs. C'est pour ça
  que le sélecteur de langue change la *matière* affichée dans la fiche d'une
  série, pas seulement un compteur ;
- la **couverture par langue** se mesure sur les lignes `tv_season` : une série
  est « présente en ar » si ses saisons ont leurs lignes `ar-SA`. C'est déjà ce
  que fait `queries.py` ;
- `source_id` d'une saison : `'1399/s2'` — l'id de série, un slash, le numéro.

La liste des langues est un réglage (`TMDB_SEASON_LANGUAGES`), pas une
constante : ne pas coder en dur `5` quelque part.

## 5. Ce qui a changé récemment dans `sourcing` (2026-08-07)

Trois choses à savoir, aucune ne casse l'admin actuel :

1. **`raw_source` ne porte plus que les références de base.** La collecte TMDB,
   plus une ligne par QID pour les séries hors TMDB (crawler). Si vous avez vu
   passer des lignes `wikipedia`/`wikidata` d'enrichissement, la migration 009
   les a purgées — l'enrichissement n'écrit plus jamais dans le brut.
2. **Deux tables nouvelles**, si l'admin veut un jour les montrer :
   - `sourcing.oeuvre` — le pivot d'identité : `id`, `univers`, et les
     identifiants externes tous nullables (`id_tmdb`, `wikidata_qid`,
     `imdb_id`, `tvmaze_id`). Une série hors TMDB y existe avec `id_tmdb` nul ;
   - `sourcing.riche_source` — l'enrichissement : une ligne par (œuvre, source,
     langue), avec `content` (texte — articles Wikipédia entre autres),
     `facts` (JSON **canonique**, mêmes clés quelle que soit la source :
     `titre`, `annee`, `statut`, `pays`, `langues`, `lieux`, `diffuseur`,
     `calendrier`, `episodes`, `ids`), `media`, et `resolved_by` (par quel
     chemin le raccordement a réussi). Les compteurs `content_chars` et
     `media_count` sont calculés — trier ou seuiller dessus est gratuit.
3. **`tmdb_catalog.first_air_date`** existe désormais (dérivée du brut par
   `tmdb dates`) — si l'admin veut trier par récence sans toucher au payload,
   c'est cette colonne, pas le `jsonb`.

## 5 bis. L'univers livres (2026-08-21) : le premier sans TMDB

Le contrat change de nature pour cet univers, et l'admin le sait par
`media.pivot_card` :

- **la vignette est keyée par le pivot** `sourcing.oeuvre.id` — il n'y a pas
  d'identifiant TMDB. `admin.livre_card` (migration 015) s'assemble depuis
  `riche_source` : libellé Wikidata en nom, article Wikipédia en synopsis
  (préférence fr, en, es, ar), faits Wikidata pour langue/pays/année ;
- **la fiche** (`fetch_work`) s'assemble de même — pas de brut à relire ;
- **les traductions affichées sont les langues d'édition Open Library**
  (`facts.editions.par_langue`), la donnée que l'univers existe pour porter ;
- le pivot gagne `id_openlibrary`, et `facts` deux clés (`auteurs`,
  `editions`) plus `ids.openlibrary` — voir architecture-sourcing §3 ;
- **pas de tableau d'avancement** : il mesure une collecte TMDB contre son
  export. `/meta` porte `acquisition: false` et le front n'affiche pas
  l'onglet.

## 6. Les invariants sur lesquels l'admin peut compter

- `raw_source` est append-only : la dernière version d'un objet est
  `order by fetched_at desc limit 1` — jamais d'UPDATE dessus ;
- ne **jamais** lire `payload` dans une requête de liste (les fiches pèsent des
  centaines de kilooctets) — c'est la règle qui a fait naître `admin.tv_card`,
  elle vaut aussi pour `riche_source.content` : listes sur `content_chars`,
  lecture du texte uniquement à la fiche ;
- `fetch_state` dit ce qui a été regardé et quand — une ligne par objet, y
  compris les échecs ; c'est là que se lit « combien de saisons attendues » ;
- un `404` dans `raw_source` est une information (série disparue de TMDB), pas
  un déchet.
