# Mission : enrichir la matière du dossier de notation

Note autonome, rédigée le 2026-08-10. Elle contient de quoi reprendre le sujet
dans un fil neuf, sans autre contexte. À lire en complément de
[`v2-notation-axes.md`](v2-notation-axes.md) (le socle des axes) et
[`admin.md`](admin.md) (les commandes).

## 1. Le constat qui déclenche la mission

La régression interne plafonne. Trois leviers ont été essayés et mesurés :

| Levier | Résultat |
|---|---|
| Volume d'œuvres notées | plafond constaté deux fois (241 → 298, puis 346 → 521) |
| Encodeur | trois candidats à 0,006 d'écart — ce n'est pas là |
| Légendes visuelles | gain réel mais encaissé, et surtout utile **au juge** |

L'erreur de validation croisée stagne autour de **0,94**, contre **0,37** de
bruit du juge lui-même (mesuré : GPT re-noté deux fois sur le même dossier
change d'avis de 0,37 en moyenne). Il reste donc ~0,57 de marge théorique, et
aucun des leviers connus ne la réduit plus.

Reste une hypothèse non testée : **le dossier lui-même est trop pauvre**.

## 2. Ce que la base contient réellement

`sourcing.riche_source`, au 2026-08-10 :

| source | lang | lignes | avec texte | texte moyen | avec `facts` | médias |
|---|---|---|---|---|---|---|
| tvmaze | — | 5 012 | 3 395 | 1 643 | 4 653 | 4 943 |
| wikidata | — | 4 803 | 0 | — | 4 425 | 0 |
| wikipedia | en | 2 576 | 2 576 | **4 544** | 0 | 0 |
| wikipedia | es | 1 012 | 1 012 | 5 205 | 0 | 0 |
| wikipedia | fr | 875 | 875 | 5 216 | 0 | 0 |
| wikipedia | ar | 442 | 442 | 2 241 | 0 | 0 |
| wikipedia | tr | 184 | 184 | 2 565 | 0 | 0 |

**Le chiffre qui commande tout le reste : seules 43 des 521 œuvres notées ont
un enrichissement, quel qu'il soit.**

L'explication est bête et entièrement réparable : `fiv-sourcing enrich`
parcourt le catalogue **par identifiant**, `fiv-admin training note` sélectionne
**par popularité**. Les deux ensembles ne se recoupent presque pas. ~90 % des
œuvres notées ont donc un dossier sans Wikipédia — ce que l'atelier affichait
depuis le début (« pas de Wikipédia — enrichir aiderait ») sans qu'on le relie
au plafond.

## 3. Ce que le dossier lit, et ce qu'il ignore

`admin/src/fiv_admin/dossier.py` fait exactement une requête sur la table :

```sql
select content from riche_source
where id_tmdb = %(id)s and source = 'wikipedia' and lang = 'en'
```

| Donnée | Lue ? |
|---|---|
| `wikipedia.content` en anglais (tronqué à 6 000 car.) | **oui** |
| `wikipedia.content` dans les autres langues | non — la notation est anglaise, décision du 2026-08-07 |
| `tvmaze.content` (résumé, 1 643 car. moyens) | **non** |
| `tvmaze.facts`, `wikidata.facts` | **non** |
| `riche_source.media` | **non** |

## 4. Le plan, du plus rentable au plus douteux

### Étape 1 — enrichir les œuvres notées (gratuit, prioritaire)

C'est la seule action dont le bénéfice est structurellement certain : elle
remplit une section que le dossier **lit déjà**, avec ~4 500 caractères par
œuvre, là où un dossier entier en fait ~5 000. La matière double.

```bash
docker compose run --rm sourcing enrich --order popularity --limit 700 --dry-run
docker compose run --rm sourcing enrich --order popularity --limit 700
```

L'ordre par popularité recouvre les œuvres notées, choisies sur le même
critère. Wikidata, Wikipédia et TVmaze sont des API publiques : le coût est nul,
seul le temps compte. La commande reprend où elle s'est arrêtée et saute les
séries déjà enrichies.

### Étape 2 — mesurer sans rien payer

```bash
docker compose run --rm admin training poids
```

Les dossiers ayant changé, leur empreinte change, donc les embeddings sont
recalculés sur la matière enrichie — **avec les anciennes notes**. C'est
exactement le test « représentation seule », et il est gratuit.

| `MAE cv` après | Conclusion |
|---|---|
| descend nettement (< 0,88) | Wikipédia nourrit l'encodeur — continuer d'enrichir, rien d'autre à faire |
| stagne (~0,94) | le bénéfice serait du côté du **juge** — voir étape 3 |

### Étape 3 — re-noter, seulement si l'étape 2 stagne (payant)

```bash
docker compose run --rm admin training note -n 200 --rejouer --legendes
docker compose run --rm admin training poids
```

~0,80 $ pour 200 œuvres. À ne faire qu'après l'étape 2 : c'est le scénario
qu'on a déjà vécu avec les légendes visuelles (§6).

### Étape 4 — ouvrir le dossier à TVmaze, si les précédentes n'ont pas suffi

À faire **avec le diagnostic**, jamais à l'aveugle :

```bash
docker compose run --rm admin training visuels
```

La même mécanique — deux dossiers qui ne diffèrent que par les sections
ajoutées — s'applique telle quelle. `comparer_visuels()` dans
`admin/src/fiv_admin/routes/training.py` et le paramètre `medias=False` de
`build_dossier()` sont le patron à copier pour tester une autre section.

**Pronostic, à vérifier plutôt qu'à croire** : les `facts` de TVmaze et de
Wikidata sont de la métadonnée — identifiants, pays, année, diffuseur,
calendrier de diffusion, nombre d'épisodes. Le peu qui touche au goût (pays,
diffuseur, année) est **déjà** dans la section FACTS du dossier, depuis TMDB.
Seul `tvmaze.content` est du texte véritable, mais souvent redondant avec le
synopsis TMDB. Attente : gain faible. C'est précisément pourquoi il faut le
mesurer avant de l'ajouter — allonger le dossier a un coût de notation.

## 5. Les commandes de contrôle

Combien d'œuvres notées ont un enrichissement :

```bash
docker compose run --rm --entrypoint python admin -c "
import asyncio, os, psycopg
async def main():
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as c:
        async with c.cursor() as cur:
            await cur.execute('''
                select rs.source, count(distinct rs.id_tmdb)
                from sourcing.riche_source rs
                where exists (select 1 from notation.score s
                              where s.id_tmdb = rs.id_tmdb and s.rubric_version = 'v2')
                group by 1 order by 2 desc
            ''')
            for r in await cur.fetchall(): print(r)
asyncio.run(main())
"
```

L'atelier le dit aussi, œuvre par œuvre : l'en-tête des onglets Training
affiche « Wikipédia en » ou « pas de Wikipédia — enrichir aiderait ».

## 6. La leçon de méthode, à ne pas réapprendre

Les légendes visuelles ont fait gagner 0,09 quand on les a activées — puis le
diagnostic a montré qu'elles n'apportaient que **0,034** à la représentation.
Les deux chiffres sont justes : le passage aux légendes changeait **deux choses
à la fois**, le dossier *et* les notes, puisque le juge re-notait avec la
section MEDIA sous les yeux. L'essentiel du gain venait des **étiquettes
obtenues** — l'axe `sensoriel`, à qui le barème interdit de se prononcer sans
preuve visuelle, cessait de rendre `null`.

D'où la règle pour toute matière ajoutée au dossier :

1. l'ajouter et **réentraîner sans re-noter** → mesure l'apport à l'encodeur ;
2. re-noter ensuite → mesure l'apport au juge ;
3. ne jamais faire les deux d'un coup, sinon les deux effets sont
   indiscernables et l'on tire la mauvaise conclusion pour la traîne.

## 7. L'état du modèle au moment d'écrire

- barème **v2**, 521 œuvres notées, écart GPT/Claude au niveau du bruit ;
- encodeur `jina-embeddings-v2-small-en`, local, 512 dimensions, 8 192 tokens ;
- `MAE cv` ≈ 0,94 avant recalibration ; la recalibration des extrêmes vient
  d'être ajoutée et le fera remonter d'environ 0,05 — c'est voulu (§ commit
  « Recalibrer les prédictions ») ;
- axe le plus faible : **`humour`, 1,25**, immobile depuis 149 œuvres,
  insensible au volume comme aux visuels. Chantier de barème (ancres,
  définition), donc une v3 — et une v3 remet le compteur d'entraînement à zéro.
