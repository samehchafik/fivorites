# Étude de couverture — marché arabophone / Golfe

> Mesure réalisée le 2026-08-05 · script : [`tools/etude_couverture_ar.py`](../tools/etude_couverture_ar.py)
> Données brutes : `etude_couverture_ar.json`
>
> **Échantillon** : 120 séries par corpus, prises par popularité décroissante (TMDB `discover`).
> C'est donc le **meilleur cas** de chaque catalogue, pas sa moyenne. Les chiffres du fond de
> catalogue sont nécessairement inférieurs.

## Corpus comparés

| Corpus | Sélection | Volume TMDB total |
|---|---|---|
| **arabophone** | `original_language=ar` | 4 898 séries |
| **golfe** | `origin_country=SA\|AE\|KW\|QA\|BH\|OM` | ~1 800 séries |
| **turc** | `original_language=tr` | 2 438 séries |
| **occidental** | `original_language=en` (témoin) | 85 058 séries |

---

## Volet 1 — Couverture texte : peut-on noter les 6 axes ?

| Indicateur | arabophone | golfe | turc | occidental |
|---|---|---|---|---|
| Texte TMDB, moyenne (car.) | 557 | 716 | 3 296 | **9 749** |
| Texte TMDB, médiane | 424 | 366 | 3 120 | 10 613 |
| Synopsis arabe présent | 78 % | 55 % | 61 % | 68 % |
| Longueur synopsis arabe | 144 | 96 | 156 | 150 |
| Traductions non vides | 2,8 | 4,1 | 8,2 | **29,9** |
| Mots-clés TMDB | 0,8 | 0,8 | 1,0 | **10,2** |
| Article Wikipédia arabe | 27 % | 19 % | 58 % | 87 % |
| Longueur article ar (car.) | 1 092 | 524 | 1 201 | 5 352 |
| **Notable** (≥ 2 000 car. cumulés) | **22 %** | **20 %** | **74 %** | **98 %** |

### Verdict

**Le catalogue arabophone et golfe n'est pas notable en l'état.** Une série sur cinq
seulement dispose d'assez de matière pour espérer une notation fiable des 6 axes. Le
synopsis arabe, quand il existe, fait 144 caractères — une phrase et demie.

Le catalogue **turc est notable à 74 %**, et se rapproche du standard occidental.

### Où la chaîne d'enrichissement casse

Le plan prévu était `TMDB → imdb_id → Wikidata (P345) → Wikipédia`. Elle rompt dès le
premier maillon :

| Corpus | a un `imdb_id` | résolu dans Wikidata | taux de résolution |
|---|---|---|---|
| arabophone | **53 %** | 27 % | 52 % |
| golfe | **41 %** | 24 % | 58 % |
| turc | 95 % | 80 % | 84 % |
| occidental | 99 % | 97 % | 98 % |

Détail sur les 120 séries arabophones :

- **56 n'ont aucun `imdb_id` dans TMDB** ← le blocage principal
- 31 ont un `imdb_id` mais aucune entité Wikidata
- 1 seule a une entité Wikidata sans article arabe

Autrement dit : ce n'est pas Wikipédia arabe qui manque, c'est **le raccordement**. Quand
l'entité existe, l'article suit dans 99 % des cas. Le problème est en amont, dans
l'identification.

---

## Volet 2 — Disponibilité visuelle : le swipe est-il jouable ?

Mesuré avec `include_image_language=ar,fr,en,null` (sans ce paramètre, TMDB ne renvoie
presque rien — cf. étude sourcing).

| Indicateur | arabophone | golfe | turc | occidental |
|---|---|---|---|---|
| Affiches, moyenne | 4,2 | 3,4 | 5,0 | **65,5** |
| Affiches, **médiane** | **2** | **2** | **3** | **57** |
| Aucune affiche | 3 % | 2 % | 22 % | 1 % |
| Fonds, moyenne | 2,9 | 3,2 | 8,1 | **76,4** |
| **Jouable** (≥1 affiche ET ≥1 fond) | **81 %** | **82 %** | **74 %** | **99 %** |

### Verdict

**Plus favorable que la couverture texte.** 8 séries arabophones sur 10 ont le minimum
vital — une affiche et un fond — donc **le swipe est jouable**.

La réserve est qualitative, pas binaire : avec une **médiane de 2 affiches** contre 57 côté
occidental, il n'y a aucune marge. Pas de repli si le visuel est médiocre, pas de choix de
format ou de langue, pas de variation possible entre la carte et la fiche. Le design de la
carte doit donc être conçu pour **un seul visuel imposé**, éventuellement de qualité
inégale — pas pour une bibliothèque dans laquelle on pioche.

Le corpus turc est le plus contrasté : 22 % sans aucune affiche, mais ceux qui en ont sont
mieux dotés (8,1 fonds en moyenne).

---

## Volet 3 — Potentiel SEO arabe

⚠️ **Aucun volume de recherche réel** (pas d'accès Keyword Planner / Ahrefs / Semrush). Ce
qui suit repose sur deux proxys libres : la **structure** des suggestions Google et les
**pages vues Wikipédia**.

### 3.1 La structure des requêtes

Suggestions Google (`hl=ar`, `gl=SA`) pour « أفضل مسلسلات » (*meilleures séries*) :

```
أفضل مسلسلات رمضان 2026          meilleures séries du Ramadan 2026
أفضل مسلسلات كورية                meilleures séries coréennes
أفضل مسلسلات خليجية رمضان 2026    meilleures séries khaleeji du Ramadan 2026
أفضل مسلسلات تركية جديدة 2026     meilleures nouvelles séries turques 2026
أفضل مسلسلات أجنبية 2025          meilleures séries étrangères 2025
أفضل مسلسلات نتفلكس 2026          meilleures séries Netflix 2026
أفضل مسلسلات عربية                meilleures séries arabes
```

**Deux enseignements structurels :**

**a) L'origine culturelle est la dimension première.** En français, « meilleures séries » se
décline par plateforme, genre et année. En arabe, elle se décline **d'abord par origine** —
turque, coréenne, khaleeji, égyptienne, syrienne, arabe, étrangère — puis par année. C'est
une dimension que la taxonomie SEO de la V1 ne possède pas du tout.

Le motif dominant est :

```
أفضل مسلسلات [origine] [année]     ≡     meilleures-series/[origine]/[année]
```

Il se branche directement sur le générateur de pages de la V1 (famille / catégorie / année),
à condition d'**ajouter l'axe « origine »** au modèle.

**b) Le Ramadan est la première suggestion**, devant tout le reste, et il apparaît aussi bien
en 2025 qu'en 2026. Ce n'est pas une intuition culturelle, c'est le premier résultat mesuré.

### 3.2 L'audience réelle par origine

Pages vues mensuelles moyennes sur **Wikipédia arabe** (12 mois, articles appariés) :

| Corpus | Médiane mensuelle | Articles arabes trouvés |
|---|---|---|
| **turc** | **14 861** | 69 / 120 |
| arabophone | 5 236 | 32 / 120 |
| occidental | 1 732 | 104 / 120 |

Exemples : *Daha 17* (« في السابعة عشرة ») 62 344 · *Güller ve Günahlar* 48 448 ·
*Eşref Rüya* 29 940 · *Uzak Şehir* 19 088 — contre *House of the Dragon* 3 887,
*Grey's Anatomy* 1 993, *Rick and Morty* 429.

**C'est le résultat le plus important de l'étude.** Le public arabophone s'intéresse
environ **8,6 fois plus** aux séries turques qu'aux séries occidentales, alors même que les
séries occidentales ont 3 fois plus d'articles arabes disponibles. L'écart n'est donc pas un
artefact de couverture — il va dans le sens inverse.

---

## Synthèse : conséquences pour la V2

### 1. Le point d'entrée est le catalogue turc, pas le catalogue arabe

Il cumule les trois avantages :

- **notable à 74 %** (contre 22 % pour l'arabophone)
- **la plus forte audience** arabophone mesurée (médiane 14 861)
- **95 % d'`imdb_id`**, donc la chaîne d'enrichissement fonctionne

Les dizi sont déjà doublées et sous-titrées en arabe, et massivement discutées. Démarrer par
là donne un catalogue exploitable immédiatement, sans source supplémentaire.

### 2. Le contenu du Golfe est le moins bien couvert de tous

20 % notable, 19 % d'article arabe, 41 % d'`imdb_id`. Si la production khaleeji est un
enjeu — et les suggestions Google montrent qu'elle est cherchée (« مسلسلات خليجية ») — il
faut une **source dédiée**, TMDB ne suffira pas. Pistes à évaluer : elCinema, Shahid (MBC),
Wikipédia arabe en recherche directe par titre plutôt que par appariement d'identifiants.

### 3. Réparer le raccordement avant d'ajouter des sources

56 séries arabophones sur 120 n'ont pas d'`imdb_id`. Avant toute nouvelle source, il faut
un **appariement par titre + année + pays** (recherche Wikipédia arabe directe), en repli
quand l'identifiant manque. C'est ce qui débloquerait le plus de volume au moindre coût.

### 4. Ajouter « origine » à la taxonomie SEO

Dimension absente de la V1, première en arabe. Elle existe déjà comme donnée
(`origin_country`, `original_language`) — mais n'est ni stockée ni exposée dans les URLs.

### 5. Le Ramadan comme cycle produit

Premier terme suggéré. Le couple `life` / `moment` de la V1 s'y branche directement :
« mes 5 séries du Ramadan » est un objet daté, comparable, renouvelé chaque année.

---

## Limites de l'étude

- **120 séries par corpus, prises au sommet de la popularité.** C'est le meilleur cas ;
  le fond de catalogue est nécessairement plus pauvre.
- **Les pages vues Wikipédia ne sont pas des volumes de recherche.** Elles mesurent un
  intérêt encyclopédique, corrélé mais non identique à l'intention commerciale.
- **Google Suggest donne une structure, pas des volumes.** L'ordre des suggestions reflète
  une popularité relative, sans échelle absolue.
- **Aucune mesure de la concurrence SEO** (nombre et qualité des sites déjà positionnés sur
  ces requêtes). C'est le chaînon manquant pour conclure sur la rentabilité réelle.
- Un seul point de mesure dans le temps, hors période de Ramadan — la saisonnalité n'est pas
  capturée.

## Pour aller plus loin

1. Rejouer sur 500-1 000 titres par corpus pour stabiliser les taux.
2. Mesurer la **concurrence** sur les 20 requêtes arabes principales (nécessite un accès
   Semrush/Ahrefs ou un scraping de SERP).
3. Tester l'appariement par titre pour les 47 % de séries arabophones sans `imdb_id`.
4. Mesurer la saisonnalité des pages vues autour du Ramadan (les données mensuelles
   Wikimedia le permettent, sur plusieurs années).
