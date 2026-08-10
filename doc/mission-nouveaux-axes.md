# Mission : ajouter six axes au barème

> **Mise à jour du 2026-08-10** — la décision prise n'a pas été d'*ajouter* six
> axes mais de **remplacer** les six existants par les dimensions de
> l'empreinte culturelle (voir
> [`mission-empreinte-culturelle.md`](mission-empreinte-culturelle.md), livré
> par la migration `009_empreinte_v1.sql`).
>
> Cette note garde toute sa valeur pour ce qui compte : **§3** (comment un axe
> est calculé, de bout en bout) et **§5** (les règles de conception, chacune
> tirée d'une panne réelle) ont directement servi à rédiger le nouveau barème.
> Seuls les §1, §4 et §7 raisonnent sur une addition plutôt qu'un remplacement.

Note de passation, rédigée le 2026-08-10. Elle est **autonome** : elle contient
tout ce qu'il faut pour concevoir six nouveaux axes et les mettre en service,
sans autre lecture. Les renvois à [`v2-notation-axes.md`](v2-notation-axes.md)
(la spécification d'origine) sont des approfondissements, pas des prérequis.

---

## 1. Ce que fait le système, en un paragraphe

Fivorites décrit chaque œuvre par un **vecteur de goût** : une liste de nombres
de 1 à 10, un par axe, obtenus en posant à un modèle de langage la même
question sur toutes les œuvres. Ce vecteur sert à situer un utilisateur dès ses
cinq premiers « fives » (démarrage à froid), à expliquer une suggestion en
français, et à passer d'un univers à l'autre (séries → livres → musique). Il ne
produit pas le classement final : il donne **la zone**, un graphe de similarité
départage à l'intérieur.

Aujourd'hui : **6 axes**, barème `v2`, **521 séries notées**. Le plan d'origine
en prévoyait **12**, à élaguer après mesure ([`v2-notation-axes.md`](v2-notation-axes.md) §9).
Ajouter six axes, c'est donc revenir au dimensionnement prévu — pas une
extension improvisée.

---

## 2. Les six axes existants

### 2.1 Le principe : un axe est une question, pas une catégorie

Pas « ce film est-il un thriller ? » (oui/non, ça n'ordonne rien) mais « quelle
est la tension de ce film, de 1 à 10 ? ». Deux thrillers peuvent être à 4 et à
9 : la mesure les sépare là où le genre les confond.

Un axe candidat qui ne peut pas se formuler comme **une question dont la
réponse est un nombre ordonné** n'est pas un axe. C'est le premier filtre, et
il élimine la moitié des idées.

### 2.2 Le tableau

| Axe | 1 | 10 |
|---|---|---|
| `luminosite` | noir, désespéré | lumineux, réparateur |
| `intensite` | doux, apaisant | bouleversant, éprouvant |
| `humour` | grave, premier degré | drôle, ironique |
| `exigence` | immédiat, évident | dense, demande un effort |
| `etrangete` | familier, balisé | singulier, déroutant |
| `sensoriel` | sobre, transparent | saturé, stylisé |

Les registres sont volontairement variés — deux affectifs (`luminosite`,
`intensite`), un tonal (`humour`), deux cognitifs (`exigence`, `etrangete`), un
formel (`sensoriel`). **Quand tous les axes viennent de la même famille, ils
finissent par se recouvrir** et l'espace perd des dimensions sans qu'on s'en
aperçoive. À garder en tête pour les six nouveaux : chercher des registres
absents plutôt que de raffiner ceux qui existent.

### 2.3 Les définitions exactes, telles qu'envoyées au juge

Reproduites depuis le barème `v2` (`admin/migrations/008_rubric_v2.sql`). Noter
la structure constante de chaque entrée : **nom → question → bornes → ce que ce
n'est pas → ancres**. La ligne « ce n'est pas » est celle qui fait le plus de
travail : c'est là que les notations dérapent.

---

**`luminosite` — Emotional luminosity.**
*Dans quel état l'œuvre vous laisse-t-elle ?*
`1 = dark, hopeless` → `10 = luminous, restorative`

> **Ce n'est pas** la tristesse de l'intrigue. Une œuvre peut dépeindre des
> atrocités et rester lumineuse parce qu'elle croit à quelque chose ; une autre
> peut ne rien raconter de grave et laisser un goût de cendre. On note
> **l'arrière-goût, pas les événements.**

Ancres : *Requiem for a Dream* = 1, *Breaking Bad* = 3, *Le Bureau des
légendes* = 5, *Parks and Recreation* = 8, *Paddington* = 10.

---

**`intensite` — Intensity.**
*À quel point l'œuvre vous secoue émotionnellement ?*
`1 = gentle, soothing` → `10 = overwhelming, gruelling`

> **Ce n'est pas** le rythme : une série au montage frénétique mais sans poids
> émotionnel reste basse. **Ce n'est pas** orienté : une œuvre euphorique et
> une œuvre dévastatrice sont toutes deux à 9 — c'est le volume de l'émotion,
> pas sa couleur. Noter **relativement aux séries**, pas à tous les médias.

Ancres : *Friends* = 1, *Le Bureau des légendes* = 5, *Sur la route de
Madison* = 10.

La précision « pas le rythme » vient d'un cas réel : sur *Rick et Morty*, GPT
donnait 7 (« frénétique ») et Claude 2 (« sans poids »). Les deux lisaient le
même dossier et répondaient à deux questions différentes.

---

**`humour` — Humour and ironic distance.**
*L'œuvre joue-t-elle, se moque-t-elle, prend-elle de la distance ?*
`1 = grave, entirely first-degree` → `10 = funny, ironic`

> **Ce n'est pas** l'étiquette de genre « comédie » : une tragédie peut être
> traversée d'ironie, une comédie peut être sinistre. On note le **régime de
> distance**, pas l'étiquette commerciale.

Ancres : *The Wire* = 2, *Game of Thrones* = 3, *Desperate Housewives* = 6,
*Fleabag* = 9.

---

**`exigence` — Cognitive demand.**
*L'œuvre se donne-t-elle immédiatement, ou demande-t-elle un effort ?*
`1 = immediate, self-evident` → `10 = dense, demands sustained attention`

> **Ce n'est pas** la qualité et **ce n'est pas** l'élitisme : une œuvre
> exigeante peut être ratée, une œuvre immédiate peut être un chef-d'œuvre. On
> note le **coût d'entrée** — densité d'information, nombre de fils, implicite
> à reconstituer.

Ancres : *Friends* = 1, *The Rookie* = 3, *Dark* = 8, *Twin Peaks* = 9.

---

**`etrangete` — Strangeness.**
*L'œuvre est-elle en territoire connu, ou vous déplace-t-elle ?*
`1 = familiar, well-trodden` → `10 = singular, disorienting`

> Deux œuvres du même genre peuvent être aux antipodes. Noter l'écart aux
> formes établies **pour un large public international**.

Ancres : *NCIS* = 1, *Stranger Things* = 5, *Twin Peaks* = 10.

C'est probablement l'axe le plus rentable du lot : le clivage de goût le plus
fort qui existe, et aucune classification par genre ne le capte.

---

**`sensoriel` — Sensory charge.**
*La forme s'efface-t-elle derrière le récit, ou vous saute-t-elle au visage ?*
`1 = sober, transparent` → `10 = saturated, stylised`

> **Ce n'est pas** le budget et **ce n'est pas** la qualité : une œuvre à
> petits moyens peut être à 10 par ambition formelle, un blockbuster à 4 par
> neutralité de mise en scène. **Règle de preuve** : juger uniquement sur les
> indices explicites du dossier — légendes MEDIA, style visuel ou d'animation
> mentionné, photographie décrite. Si le dossier ne dit rien de la forme,
> préférer `null` à une supposition tirée du genre.

Ancres : *Columbo* = 2, *House of the Dragon* = 7, *Euphoria* = 9.

---

### 2.4 Deux règles transversales du barème

Elles s'appliquent à tous les axes et devront s'appliquer aux nouveaux :

1. **Calibration.** « La télévision courante vit en zone 4-6 ; les extrêmes se
   méritent. » Sans cette phrase, les juges se collent aux bornes et l'échelle
   s'écrase.
2. **Le droit de ne pas savoir.** Chaque note porte une confiance de 0 à 1, et
   `null` est une réponse valide et attendue. **Un vecteur absent vaut mieux
   qu'un vecteur inventé** — un `null` se rattrape, une valeur inventée pollue
   l'entraînement en silence.

### 2.5 Deux axes ont été écartés du socle — ne pas les re-proposer

**Tension** (contemplatif ↔ haletant) → devenu **axe contextuel**. Ce n'est pas
un trait de goût, c'est une humeur : quelqu'un qui aime le cinéma contemplatif
veut quand même un thriller certains soirs. La luminosité qu'on aime ne bouge
pas d'un mois sur l'autre ; l'envie d'être tenu en haleine change d'un jour à
l'autre. Un axe contextuel se note, mais **n'entre ni dans le profil ni dans la
distance** — il sert à la requête (« ce soir j'ai envie de… »).

**Échelle** (intime ↔ collectif) → **facette spécifique écran/papier**. L'axe ne
tient pas en musique, et un axe qui échoue sur un univers ne peut pas servir au
cross-média — ce qui est précisément la fonction du socle.

> **Conséquence pour la mission** : un axe candidat doit passer un test de
> stabilité (« est-ce un trait durable ou une humeur ? ») et un test
> d'universalité (« tient-il en musique, en BD, en littérature ? »). S'il
> échoue au premier, c'est un axe contextuel ; au second, une facette. Les deux
> catégories sont utiles — mais elles ne vont pas dans le socle, et le socle
> est le seul espace où l'on calcule des distances.

---

## 3. Comment un axe est calculé

Deux étages successifs, à ne pas confondre.

### 3.1 Étage 1 — le juge (LLM), sur la tête du catalogue

```
œuvre ──► build_dossier() ──► prompt du barème ──► GPT ──► JSON ──► notation.score
                                                   │
                                                   └─ contre-juge Claude ──► training_run.claude
```

**Le dossier** (`admin/src/fiv_admin/dossier.py`) est le texte anglais soumis au
juge. Ses sections, dans l'ordre :

| Section | Contenu | Poids typique |
|---|---|---|
| `TITLE` / `ORIGINAL TITLE` | titres | — |
| `FACTS` | année, pays, statut, nombre de saisons/épisodes, chaîne | court |
| `MATERIAL` | ce dont le dossier dispose (méta-information honnête) | court |
| `GENRES`, `KEYWORDS` | tags TMDB — plus fins que les genres seuls | court |
| `OVERVIEW` | le pitch marketing | 150-400 car. |
| `SEASON OVERVIEWS` | résumé par saison | variable |
| `EPISODE SYNOPSES` | échantillonnés sur toute la série | ⭐ la matière principale |
| `WIKIPEDIA (en)` | intrigue détaillée + accueil critique | ~4 500 car. quand présent |
| `MEDIA` | légendes d'images, **optionnel** (`--legendes`) | court mais décisif pour `sensoriel` |

**Ce que ça implique pour un nouvel axe** : le juge ne voit que ça. Un axe qui
demande une information absente du dossier ne produira jamais de signal, quelle
que soit la qualité de sa définition. C'est le piège n°1, développé en §5.3.

Le prompt complet est **une colonne de la base**, pas un fichier :
`notation.rubric.prompt`. Le barème est versionné, et la version fait partie de
la provenance de chaque note.

### 3.2 Étage 2 — la régression interne, pour la traîne

Faire noter 300 000 séries par un LLM coûte trop cher. On note donc la tête, et
on **distille** : un modèle local apprend à retrouver les notes du juge à partir
du texte seul.

```
dossier ──► encodeur local (ONNX) ──► vecteur 512 dims ──► ridge par axe ──► note prédite
```

- **Encodeur** : `jinaai/jina-embeddings-v2-small-en`, 512 dimensions, fenêtre
  8 192 tokens, en local, coût nul. Choisi le 2026-08-10 après mesure contre
  `nomic-v1.5` et `bge-small` : égalité à 0,006 près — la représentation n'est
  pas le goulot.
- **Une régression ridge indépendante par axe** (`admin/src/fiv_admin/weights.py`,
  `train_axis()`). λ choisi par validation croisée k-fold avec réajustement à
  chaque pli — la forme close « leave-one-out » dégénère quand il y a moins
  d'œuvres que de dimensions, ce qui est notre cas.
- **Recalibration** : la ridge contracte les prédictions vers la moyenne (pente
  mesurée 0,49-0,68 sur les prédictions hors-pli). L'inverse de cette pente est
  replié dans les coefficients, sinon les extrêmes — précisément ce qui
  distingue les goûts — sont écrasés.
- **Seuil** : `MIN_TRAINING_WORKS = 10`. En dessous, l'axe est marqué `skipped`
  et n'est simplement pas entraîné. Un nouvel axe sans notes ne casse rien : il
  est ignoré jusqu'à ce qu'il ait de la matière.

### 3.3 Les chiffres de référence, au 2026-08-10

| Grandeur | Valeur | Lecture |
|---|---|---|
| Œuvres notées, barème v2 | 521 | |
| `MAE cv` moyen, régression interne | **≈ 0,94** | sur une échelle de 1 à 10 |
| Bruit propre du juge (test-retest GPT) | **0,37** | le plancher théorique |
| Écart moyen GPT / Claude, v1 → v2 | 1,32 → **0,96** | ce que les ancres ont gagné |
| Axe le plus faible | `humour`, **1,25** | immobile malgré volume et visuels |

Le plancher à 0,37 est important : **aucun axe ne peut faire mieux que le
désaccord du juge avec lui-même.** Un nouvel axe qui atteint 0,6 est excellent ;
un axe à 1,3 est cassé.

---

## 4. Ce qu'il faut modifier pour ajouter six axes

Bonne nouvelle : **presque rien de technique**. Le système a été écrit pour que
la liste des axes soit une donnée, pas du code.

### 4.1 Ce qui est déjà dynamique — ne rien y toucher

- `notation.score` a **une ligne par (œuvre, axe)**, pas une colonne par axe.
  Ajouter un axe n'est pas une migration de schéma.
- Tout le back lit `rubric["axes"]` (`admin/src/fiv_admin/routes/training.py`
  lignes 858, 939, 1016, 1220). L'entraînement boucle sur cette liste.
- `notation.weights` a `axe` en clé primaire composite : un jeu de poids par
  axe, créé à la volée.
- Le front dégrade proprement : `AxisVector.tsx` connaît six clés pour l'ordre
  et le libellé français, et **affiche quand même** tout axe inconnu, avec son
  nom brut.

### 4.2 Ce qu'il faut écrire

**Une migration, `admin/migrations/009_rubric_v3.sql`**, qui insère une nouvelle
ligne dans `notation.rubric` :

```sql
insert into notation.rubric (version, prompt, axes, note) values (
    'v3',
    'You are a cultural-work rater. …',   -- le prompt complet, 12 axes
    '["luminosite", "intensite", "humour", "exigence", "etrangete", "sensoriel",
      "…", "…", "…", "…", "…", "…"]'::jsonb,
    'Douze axes — les six du socle v2 plus six nouveaux. …'
);
```

**Ne jamais modifier `v2` en place.** La version *est* la provenance : une note
v2 doit rester interprétable avec le prompt v2, indéfiniment. Le sélecteur de
l'atelier propose la version la plus récente en premier, donc `v3` devient le
défaut sans autre geste.

**Six lignes dans `front/src/components/AxisVector.tsx`**, pour le libellé
français et l'ordre d'affichage :

```ts
const KNOWN_AXES = [
  { key: 'luminosite', label: 'Luminosité' },
  …
  { key: 'nouveau', label: 'Nouveau' },
]
```

C'est tout. Pas de migration de table, pas de changement de route, pas de
changement dans la régression.

### 4.3 Le vrai coût : une v3 remet le compteur d'entraînement à zéro

L'entraînement filtre sur `rubric_version`. Les 521 œuvres notées en v2 ne
comptent pas pour la v3 — il faut les **renoter**.

```bash
docker compose run --rm admin training note -n 521 --rejouer --legendes --bareme v3
docker compose run --rm admin training poids
```

Ordre de grandeur : **~2 $** pour 521 œuvres avec légendes. Le coût réel est le
temps, pas l'argent. Mais il y a une conséquence de méthode plus sérieuse :
**tant que la v3 n'a pas rattrapé le volume de la v2, on ne peut pas comparer
leurs performances.** Prévoir de renoter le lot complet avant de conclure quoi
que ce soit sur la qualité des nouveaux axes.

---

## 5. Les règles de conception, apprises à nos frais

Chacune vient d'une panne réelle. C'est la partie la plus utile de cette note.

### 5.1 Sans ancres, un axe diverge — c'est mesuré

Le premier lot réel (13 œuvres, contre-notées en v1) a donné, par axe :

| Axe | Écart GPT/Claude | Ancré en v1 ? |
|---|---|---|
| `exigence` | 0,67 | non |
| `luminosite` | **0,83** | **oui** |
| `humour` | 1,17 | non |
| `etrangete` | 1,42 | non |
| `intensite` | **1,50** | **oui** |
| `sensoriel` | **2,75** — cassé | non |

Le motif dominant : **les axes ancrés convergent, les axes sans ancres
divergent** (`intensite` faisait exception, pour une raison de définition, pas
d'ancrage — voir 5.2). Ajouter des ancres aux quatre axes qui n'en avaient pas
a fait passer l'écart moyen de 1,32 à 0,96.

**Règle : trois à cinq ancres par axe, minimum, dès la première version.** Un
axe non ancré n'est pas « à raffiner plus tard », il est inutilisable.

### 5.2 Les ancres doivent couvrir toute la portée, sans trou ni doublon

Regarder ce que la v2 fait vraiment :

| Axe | Ancres | Défaut |
|---|---|---|
| `luminosite` | 1, 3, 5, 8, 10 | ✅ irréprochable |
| `intensite` | 1, 5, 10 | ✅ portée complète |
| `etrangete` | 1, 5, 10 | ✅ portée complète |
| `humour` | 2, 3, 6, 9 | ⚠️ ni 1 ni 10 ; **2 et 3 redondants** (*The Wire*, *Game of Thrones* — deux drames graves de prestige, deux emplacements gâchés sur la même région) ; trou de 3 à 6, là où vivent la plupart des comédies |
| `exigence` | 1, 3, 8, 9 | ⚠️ trou de 3 à 8 — tout le milieu |
| `sensoriel` | 2, 7, 9 | ⚠️ ni 1 ni 10 |

Le pire jeu d'ancres et le pire axe mesuré sont le même : `humour`. Ce n'est
probablement pas une coïncidence.

**Règle : une ancre près de 1, une près de 10, une au milieu, et jamais deux
ancres dans la même région.**

### 5.3 Une ancre partagée entre deux axes leur enseigne de corréler

*Twin Peaks* est ancre à `exigence = 9` **et** à `etrangete = 10`. Or la
question ouverte n°1 de la spécification est précisément : *ces deux axes
n'en font-ils qu'un ?*

Le jeu d'ancres **fabrique** donc en partie la corrélation qu'on cherche à
mesurer. Si l'on calcule `corr(exigence, etrangete)` sur les notes v2 et qu'on
la trouve forte, on ne saura pas dire si c'est le monde ou la consigne.

**Règle : deux axes ne partagent jamais une œuvre-ancre.** Et si l'on veut
trancher la fusion `exigence` × `etrangete`, il faut d'abord dé-corréler leurs
ancres.

*(Cas moins graves, à corriger tant qu'on y est : `Friends` ancre `intensite`=1
et `exigence`=1 ; `Le Bureau des légendes` ancre `luminosite`=5 et
`intensite`=5.)*

### 5.4 Un axe ne peut pas mesurer ce que le dossier ne contient pas

`humour` est à **1,25** et n'a pas bougé d'un pouce quand on est passé de 149 à
521 œuvres, ni quand on a ajouté les légendes visuelles, ni en changeant
d'encodeur. Trois leviers, aucun effet.

L'explication tient au matériau : **un dossier décrit ce qui se passe, pas
comment c'est joué.** Le synopsis de *It's Always Sunny in Philadelphia* se lit
comme la chronique de gens abjects commettant des actes abjects ; rien dans le
texte ne dit que c'est drôle. Le ton est porté par le jeu, le montage, le
rythme — précisément ce qu'un résumé d'intrigue laisse tomber.

**Règle : pour chaque axe candidat, écrire noir sur blanc quelle section du
dossier (§3.1) portera le signal.** Si la réponse est « aucune, il faudrait
avoir vu l'œuvre », l'axe échouera — non pas parce qu'il est mal défini, mais
parce que le matériau est muet. Les seules sections qui portent du **ton** sont
`KEYWORDS` (TMDB tague `satire`, `black comedy`, `deadpan`) et la partie
*accueil critique* de `WIKIPEDIA` — c'est-à-dire les endroits où quelqu'un
**parle de** l'œuvre au lieu de la **résumer**.

### 5.5 Si un axe dépend d'un matériau parfois absent, lui donner une règle de preuve

`sensoriel` était l'axe le plus cassé de la v1 : 2,75 d'écart, GPT au-dessus de
Claude 11 fois sur 12, écarts jusqu'à 5 points. Les deux juges devinaient la
forme à partir du genre, dans des directions opposées.

La correction n'a pas été une meilleure définition mais une **règle de preuve** :
juger uniquement sur des indices explicites, sinon `null`. Conséquence assumée :
sans section `MEDIA`, l'axe se tait presque partout.

**Règle : tout axe dont le signal peut manquer doit dire explicitement quelles
sections font preuve, et préférer `null` à la déduction par le genre.**

### 5.6 Noter relativement à son univers

Le format long amplifie mécaniquement l'intensité : sans la mention « noter
relativement aux séries, pas à tous les médias », toutes les musiques finissent
basses et toutes les séries hautes. Le stockage reste **brut** (1 à 10 tel que
noté) ; la normalisation par univers (z-score, rang percentile) est un calcul de
lecture, pas une donnée — elle dépend du corpus, qui change.

### 5.7 Ne jamais changer deux choses à la fois

Les légendes visuelles ont paru faire gagner 0,09. Le diagnostic isolé a montré
qu'elles n'apportaient que **0,034** à la représentation. Les deux mesures sont
justes : le passage aux légendes changeait le dossier **et** les notes, puisque
le juge renotait avec la section `MEDIA` sous les yeux. L'essentiel du gain
venait des **étiquettes obtenues** — `sensoriel` cessait de rendre `null`.

**Règle, pour toute modification du barème :** ajouter la matière et
réentraîner *sans* renoter (mesure l'apport à l'encodeur), puis renoter (mesure
l'apport au juge). Jamais les deux d'un coup, sinon les deux effets sont
indiscernables et l'on tire la mauvaise conclusion.

---

## 6. Comment valider les six nouveaux axes

Trois tests, dans cet ordre, **avant** d'ouvrir les axes au produit.

**a) Fidélité test-retest.** Noter 100 œuvres deux fois avec le même prompt.
Écart moyen attendu **< 1 point**, et l'objectif est de s'approcher de 0,37.
Au-delà de 1, c'est la **formulation de l'axe** qu'il faut reprendre — pas le
modèle, pas le volume.

**b) Contre-juge.** Faire noter le même lot par un modèle d'une autre famille
(Claude) et comparer axe par axe. Un désaccord entre familles révèle une
question ambiguë ; un accord ne prouve pas la justesse, mais son absence prouve
le problème. Les notes `modele like 'claude%'` sont exclues de l'entraînement —
le contre-juge mesure, il n'enseigne pas.

**c) Indépendance.** Matrice de corrélation sur les 12 axes, puis ACP. **C'est
le test décisif de cette mission** : si les 12 axes se réduisent à 4 ou 5
composantes, les six nouveaux ne mesurent rien de neuf et il vaut mieux le
savoir avant d'avoir payé la notation complète. Attention au biais de la §5.3 —
la matrice ne vaut que si les jeux d'ancres sont disjoints.

Un axe qui échoue à (c) ne se répare pas : il se supprime. C'est ainsi qu'on
était passé de 12 candidats à 6.

Et deux contrôles de bout en bout, gratuits parce que les données sont déjà en
base :

- **Validité externe** — `similar_tmdb_raw` et `recommendations_tmdb_raw` :
  deux séries que TMDB juge similaires doivent être proches dans l'espace des
  axes.
- **Reconstitution des fives** — masquer un des 5 fives d'un membre V1 ; le
  système le remonte-t-il dans le top 50 ? C'est la métrique qui décide, et
  elle est mesurable dès aujourd'hui.

---

## 7. Marche à suivre

1. **Proposer 6 axes candidats.** Pour chacun : la question, les deux bornes,
   la ligne « ce n'est pas », 3 à 5 ancres couvrant toute la portée, et
   **la section du dossier qui portera le signal** (§5.4). Vérifier qu'aucune
   ancre n'est déjà utilisée par un autre axe (§5.3), et que l'axe passe les
   tests de stabilité et d'universalité (§2.5).
2. **Écrire `009_rubric_v3.sql`** — prompt complet à 12 axes, `axes` en jsonb,
   `note` expliquant ce qui change et pourquoi. Ne pas toucher à `v2`.
3. **Ajouter les 6 libellés** dans `AxisVector.tsx`.
4. **Noter un petit lot** (30-50 œuvres) en v3, examiner les notes à la main
   dans l'atelier — les aberrations se voient à l'œil bien avant les moyennes.
5. **Contre-noter** ce lot et corriger les définitions qui divergent. Itérer
   ici, c'est peu coûteux ; itérer après 500 œuvres, non.
6. **Renoter le lot complet** (§4.3), puis `training poids`.
7. **Passer les trois tests** du §6 et élaguer.

Les étapes 4 et 5 sont celles qu'on avait sautées en v1, et c'est ce qui a
coûté une v2.

---

## 8. Où regarder dans le dépôt

| Quoi | Où |
|---|---|
| La spécification d'origine (12 axes candidats, cross-média, vecteur utilisateur) | [`doc/v2-notation-axes.md`](v2-notation-axes.md) |
| Le barème actuel, prompt complet | `admin/migrations/008_rubric_v2.sql` |
| Le schéma de notation | `admin/migrations/003_notation.sql` |
| L'assemblage du dossier soumis au juge | `admin/src/fiv_admin/dossier.py` |
| Notation, entraînement, diagnostics (couche partagée CLI + front) | `admin/src/fiv_admin/routes/training.py` |
| La régression ridge, la CV, la recalibration | `admin/src/fiv_admin/weights.py` |
| L'encodeur local | `admin/src/fiv_admin/embed.py` |
| L'affichage du vecteur | `front/src/components/AxisVector.tsx` |
| Les commandes | [`doc/admin.md`](admin.md) |
| L'itération sur le prompt | [`doc/mission-ajustement-prompt.md`](mission-ajustement-prompt.md) |
| L'enrichissement du dossier (lié à §5.4) | [`doc/mission-enrichissement-dossier.md`](mission-enrichissement-dossier.md) |
