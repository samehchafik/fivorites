# Le système de notation — des axes au vecteur

> Spécification de la **couche 2** (les axes de goût). La couche 1 (collecte) est décrite
> dans [`v2-acquisition-series.md`](v2-acquisition-series.md) et implémentée dans
> `sourcing/`. La couche 3 (facettes d'usage) est déduite des deux premières et n'a pas
> de stockage propre.
>
> Les décisions marquées ⚠️ ne sont pas tranchées et attendent une mesure.

---

## 1. Le principe

### 1.1 Un axe, c'est une question

Un axe n'est pas une catégorie, c'est une **mesure** : une question posée à l'identique sur
toutes les œuvres, dont la réponse est un nombre.

Pas « ce film est-il un thriller ? » (oui/non, ça n'ordonne rien) mais « quelle est la
tension de ce film, de 1 à 10 ? ». La différence est décisive : deux thrillers peuvent avoir
des tensions de 4 et de 9, et la mesure le dit là où le genre l'écrase.

### 1.2 Le vecteur, c'est la liste des réponses

Une œuvre = 6 nombres. Rien de plus.

| | Luminosité | Intensité | Humour | Exigence | Étrangeté | Sensoriel |
|---|---|---|---|---|---|---|
| Breaking Bad | 2 | 9 | 4 | 6 | 5 | 6 |
| Twin Peaks | 4 | 6 | 6 | 9 | 10 | 8 |
| Friends | 9 | 2 | 9 | 1 | 2 | 3 |

*(valeurs d'illustration, pas des mesures)*

Trois lignes, et on sépare déjà des œuvres qu'aucune taxonomie de genres ne sépare.

### 1.3 Ce que le vecteur fait — et ne fait pas

**Il fait** trois choses que le graphe communautaire seul ne sait pas faire :

- **le démarrage à froid** — 5 fives suffisent à situer quelqu'un, aucun besoin de masse critique
- **l'explication** — « vous aimez les univers sombres et singuliers » est une phrase affichable
- **le passage d'un univers à l'autre** — les 6 axes sont communs aux 5 familles

**Il ne fait pas** le classement final. Six axes à dix niveaux, c'est un espace **petit** :
beaucoup d'œuvres tombent au même endroit. C'est assumé — c'est ce qui le rend interprétable
et robuste avec peu de données. Le vecteur donne **la zone**, le graphe départage **à
l'intérieur**. Lui demander de tout faire, c'est le casser.

---

## 2. Les 6 axes retenus

Socle commun aux cinq univers. C'est le seul espace où l'on calcule des distances.

| Axe | 1 | 10 |
|---|---|---|
| **Luminosité** | noir, désespéré | lumineux, réparateur |
| **Intensité** | doux, apaisant | bouleversant, éprouvant |
| **Humour** | grave, premier degré | drôle, ironique |
| **Exigence** | immédiat, évident | dense, demande un effort |
| **Étrangeté** | familier, balisé | singulier, déroutant |
| **Charge sensorielle** | sobre, transparent | saturé, stylisé |

Ils couvrent des registres différents — deux affectifs, un tonal, deux cognitifs, un formel.
C'est un signe de santé : quand tous les axes viennent de la même famille, ils finissent par
se recouvrir.

### 2.1 Deux axes ont été sortis du socle

**Tension** (contemplatif ↔ haletant) → **axe contextuel**. Ce n'est pas un trait de goût,
c'est une humeur : quelqu'un qui aime le cinéma contemplatif veut quand même un thriller
certains soirs. La luminosité qu'on aime ne bouge pas d'un mois sur l'autre, l'envie d'être
tenu en haleine change d'un jour à l'autre. On le note quand même sur les œuvres, mais il
n'entre **ni dans le profil, ni dans la distance** — il sert à la requête (« ce soir j'ai
envie de… »). Effet de bord utile : ça supprime le risque de confusion avec l'intensité.

**Échelle** (intime ↔ collectif) → **facette spécifique écran/papier**. L'axe ne tient pas en
musique, or un axe qui échoue sur un univers ne peut pas servir au cross-média — c'est
précisément la fonction du socle. Il reste excellent pour affiner à l'intérieur des séries,
films, livres et BD.

### 2.2 Définitions détaillées

Chaque définition sert directement de consigne de notation. La ligne **« ce n'est pas »**
est la plus importante : c'est là que les notations dérapent.

---

#### Luminosité affective

> *Dans quel état l'œuvre vous laisse-t-elle ? Quel regard porte-t-elle sur le monde ?*
> `1 = noire, désespérée` → `10 = lumineuse, réparatrice`

**Ce n'est pas** la tristesse des événements. Une œuvre peut raconter des choses atroces et
rester lumineuse, parce qu'elle croit à quelque chose ; une autre peut ne rien raconter de
grave et laisser un goût de cendre. On note **l'arrière-goût, pas l'intrigue**. C'est la
question la plus mal comprise des six — à dire explicitement dans la consigne.

| | 1 | 5 | 10 |
|---|---|---|---|
| Écran | *Requiem for a Dream* | *Lost in Translation* | *Paddington 2* |
| Papier | *La Route* | *L'Étranger* | *Astérix* |
| Musique | *Closer*, Joy Division | *Kind of Blue* | *Songs in the Key of Life* |

---

#### Intensité

> *À quel point l'œuvre vous secoue ? Quelle est l'amplitude de ce qu'elle fait ressentir ?*
> `1 = douce, apaisante` → `10 = bouleversante, éprouvante`

**Ce n'est pas** orienté. Un album euphorique et un film dévastateur sont tous deux à 9 :
c'est le volume de l'émotion, pas sa couleur — la couleur, c'est la luminosité. Une œuvre à
`luminosité 9 / intensité 9` existe : c'est la joie qui vous met par terre.

⚠️ **Piège de format** : le format long amplifie mécaniquement l'intensité. Noter
**relativement à son propre univers**, sinon toutes les musiques finissent basses et toutes
les séries hautes.

| | 1 | 5 | 10 |
|---|---|---|---|
| Écran | *Friends* | *Le Bureau des légendes* | *Sur la route de Madison* |
| Papier | *Le Chat* | *Le Nom de la rose* | *Une vie comme les autres* |
| Musique | Erik Satie | *Rumours* | *Mad World* |

---

#### Humour

> *L'œuvre joue-t-elle, se moque-t-elle, prend-elle de la distance ?*
> `1 = grave, au premier degré` → `10 = drôle, ironique`

**Ce n'est pas** le genre « comédie ». Une tragédie peut être traversée d'ironie, une comédie
peut être sinistre. On note le **régime de distance**, pas l'étiquette commerciale.

⚠️ **L'axe qui voyage le plus mal d'une culture à l'autre.** Ce qui est drôle est
culturellement situé bien plus que ce qui est sombre ou intense. À surveiller en priorité si
le catalogue s'ouvre à d'autres aires (cf. [étude marché arabe](etude-couverture-marche-arabe.md)).

---

#### Exigence

> *L'œuvre se donne-t-elle immédiatement, ou demande-t-elle un effort ?*
> `1 = immédiate, évidente` → `10 = dense, exige de l'attention`

**Ce n'est pas** la qualité, et ce n'est pas l'élitisme. Une œuvre exigeante peut être ratée,
une œuvre immédiate peut être un chef-d'œuvre. On note le **coût d'entrée** : densité
d'information, nombre de fils, implicite à reconstituer.

---

#### Étrangeté

> *L'œuvre est-elle dans un territoire connu, ou vous déplace-t-elle ?*
> `1 = familier, balisé` → `10 = singulier, déroutant`

Probablement l'axe le plus rentable du lot : c'est le clivage de goût le plus fort qui existe
et aucune classification par genre ne le capte. Deux films de science-fiction peuvent être
aux antipodes dessus.

⚠️ **L'étrangeté est relative, pas absolue.** « Familier » se mesure par rapport à un
référentiel culturel : un drama coréen est étrange pour un spectateur français, familier pour
quelqu'un qui en consomme depuis dix ans. Si le produit vise plusieurs marchés, cet axe doit
être **normalisé par population de référence**, pas noté dans l'absolu. À prévoir dans le
modèle de données dès maintenant (cf. §6.2).

---

#### Charge sensorielle

> *L'œuvre s'efface-t-elle derrière ce qu'elle raconte, ou sa forme vous saute-t-elle au visage ?*
> `1 = sobre, transparente` → `10 = saturée, stylisée`

**Ce n'est pas** le budget, et ce n'est pas la qualité. Un film à petits moyens peut être à 10
par parti pris formel ; un blockbuster peut être à 4 parce que sa mise en scène est neutre.
La question est : **est-ce que la forme se fait remarquer ?**

⚠️ **Reformulation obligatoire en musique**, sinon tout est à 10 : l'axe devient la **densité
de production** — enregistrement acoustique nu à 1, mur de son orchestré et saturé à 10.

| | 1 | 5 | 10 |
|---|---|---|---|
| Écran | les frères Dardenne | un film classique bien tenu | *Blade Runner 2049* |
| Papier | Simenon | un roman classique | Céline, *Little Nemo* |
| Musique | Nick Drake voix-guitare | une pop bien produite | *My Bloody Valentine* |

### 2.3 Les frottements à surveiller

| Paire | Risque | Que faire |
|---|---|---|
| **Exigence × Étrangeté** | 🔴 élevé — ce qui est singulier est souvent difficile | ⚠️ décision différée, cf. §5.3 |
| Intensité × Sensoriel | 🟠 moyen — le spectaculaire produit de l'intensité | corrélation réelle mais partielle, garder |
| Luminosité × Intensité | 🟢 faible — les œuvres très sombres sont rarement douces | attendu, sans gravité |

---

## 3. Comment on obtient les nombres

### 3.1 L'ancrage est le point critique

Si on demande à un modèle « note la tristesse de 1 à 10 », il répond 6 ou 7 pour à peu près
tout, et deux notations du même titre à deux jours d'écart divergent. **Des nombres non
comparables entre eux ne servent à rien** : toute la métrique repose sur leur comparabilité.

La solution est de **définir l'échelle par des œuvres de référence** dans la consigne :

```
Luminosité affective
  1  Requiem for a Dream
  3  Breaking Bad
  5  Le Bureau des légendes
  8  Parks and Recreation
 10  Paddington 2

Où placer cette œuvre sur cette échelle ?
```

La question devient une **comparaison**, et une comparaison est stable. Trois à cinq ancres
par axe suffisent.

**Il faut un jeu d'ancres par univers** — les ancres séries ne calibrent pas la musique — et
⚠️ **par aire culturelle** si le catalogue s'ouvre : les ancres occidentales ne calibrent rien
pour un annotateur qui note du contenu turc ou khaleeji.

Les ancres sont **versionnées** : changer une ancre change toutes les notations qui en
découlent, donc `rubric_version` fait partie de la provenance (§4.1).

### 3.2 Ce qu'on donne à lire au modèle

L'[étude de couverture](etude-couverture-marche-arabe.md) a mesuré ce qui est réellement
disponible. Par ordre de valeur :

| Source | Volume typique | Remarque |
|---|---|---|
| **Synopsis d'épisodes** | ⭐ 16 000–75 000 car. | déjà collecté, ×25 sur le reste. Décrit l'arc réel, pas le pitch |
| Wikipédia (fr/en) | 5 000–30 000 car. | intrigue détaillée + accueil critique |
| `translations` TMDB | ~11 000 car. cumulés | ~45 synopsis rédigés indépendamment, réellement variés |
| Mots-clés TMDB | 5–30 termes | tagging communautaire, plus fin que les genres |
| Overview série | 150–400 car. | le pitch marketing — le moins utile |

**Deux règles de collecte :**

1. **Ne pas filtrer par langue à la collecte.** Un modèle de notation lit l'arabe et le turc
   aussi bien que l'anglais ; la contrainte linguistique porte sur le *volume disponible*, pas
   sur la capacité. Filtrer à la collecte coûte un re-téléchargement pour revenir en arrière ;
   filtrer à la notation coûte une relecture de table.
2. **La langue de notation et la langue de présentation sont deux problèmes séparés.** On note
   avec ce qui existe, on traduit à l'affichage.

### 3.3 Le budget : noter la tête, distiller la traîne

Sur 228 370 séries dans TMDB, l'immense majorité n'a aucune matière. Il ne s'agit pas de tout
noter mais de **choisir ce qui entre au catalogue**.

```
 tête (~50 k titres)   → notation LLM complète, avec ancres           coût réel
 traîne notable        → modèle léger distillé : texte → 6 nombres    coût ~nul
 traîne sans matière   → pas de vecteur, et c'est très bien
```

Le modèle distillé s'entraîne sur les notations de la tête. Il n'invente rien, il généralise.

### 3.4 Le droit de ne pas savoir

**Un vecteur absent vaut mieux qu'un vecteur inventé.** La consigne doit autoriser
explicitement `null` avec un motif, et chaque note porte une **confiance** :

| Confiance | Situation |
|---|---|
| élevée | plusieurs milliers de caractères, œuvre identifiée sans ambiguïté |
| moyenne | matière limitée mais cohérente |
| faible | overview seul, ou signaux contradictoires |
| `null` | pas assez de matière — **ne pas noter** |

Le seuil d'entrée en production se règle sur la confiance, pas sur l'existence de la note.

### 3.5 Contrôle qualité

Trois tests, à faire **avant** de noter le catalogue entier :

**a) Fidélité test-retest.** Noter 100 œuvres deux fois. Écart moyen attendu **< 1 point**.
Au-delà, c'est la **formulation de l'axe** qu'il faut reprendre — pas le modèle.

**b) Indépendance.** Matrice de corrélation sur ~300 œuvres, puis ACP. Si les 6 axes se
réduisent à 3 composantes, on a 3 axes : il faut le savoir avant d'avoir payé la notation
complète.

**c) Validité externe.** `similar_tmdb_raw` et `recommendations_tmdb_raw` sont déjà en base :
deux séries que TMDB juge similaires doivent être proches dans l'espace à 6 dimensions. Jeu
d'évaluation gratuit, disponible immédiatement, sans annotation manuelle.

---

## 4. Le stockage

### 4.1 Le schéma

```sql
-- Schéma `notation` : la couche 2.
-- Une ligne par (œuvre, axe, version de barème). On ne remplace jamais une
-- notation : on en ajoute une nouvelle et on lit la plus récente. Ça permet de
-- comparer deux barèmes ou deux modèles sans rien perdre.

create schema if not exists notation;

create table notation.rubric (
    version      text        primary key,   -- 'v1', 'v2-ancres-turc'
    axes         jsonb       not null,      -- définitions + ancres par univers
    created_at   timestamptz not null default now(),
    note         text
);

create table notation.score (
    oeuvre_id      bigint      not null,
    univers        text        not null,    -- series | movies | books | bd | musics
    axe            text        not null,    -- luminosite | intensite | humour | exigence | etrangete | sensoriel
    valeur         numeric(3,1),            -- 1.0 à 10.0 — null = « ne sait pas »
    confiance      numeric(3,2) not null,   -- 0.00 à 1.00
    motif_null     text,                    -- renseigné ssi valeur is null
    rubric_version text        not null references notation.rubric(version),
    modele         text        not null,    -- identifiant exact du modèle
    input_sha256   bytea       not null,    -- hash du texte soumis : rejouabilité
    scored_at      timestamptz not null default now(),
    primary key (oeuvre_id, univers, axe, rubric_version, modele, scored_at)
);

-- La lecture courante : la dernière notation valide par œuvre et par axe.
create index score_courant_idx
    on notation.score (oeuvre_id, univers, axe, scored_at desc)
    where valeur is not null;
```

**Pourquoi une ligne par axe** plutôt que six colonnes : un axe peut être renoté seul, être
absent, ou disparaître du barème. Le format long encaisse tout ça sans migration.

**Pourquoi `input_sha256`** : c'est ce qui permet de dire « cette note a été produite à partir
de ce texte-là ». Sans lui, impossible de savoir si une divergence vient du modèle ou d'un
enrichissement de la source.

### 4.2 Brut ou normalisé ?

**On stocke le brut** (1 à 10, tel que noté). La normalisation est un calcul, pas une donnée :
elle dépend du corpus de référence, qui change quand le catalogue grossit.

Deux normalisations utiles, calculées à la lecture ou matérialisées en vue :

- **z-score par univers** — `z = (x − μ_univers) / σ_univers`. Indispensable au cross-média :
  ce qui se transfère, c'est « très sombre **pour une série** » → « très sombre **pour un
  livre** », pas la valeur absolue.
- **rang percentile** — plus robuste aux distributions asymétriques, plus lisible pour
  l'affichage (« parmi les 10 % les plus sombres »).

⚠️ Sans normalisation par univers, une recherche cross-média remonte les œuvres les plus
**moyennes** de l'univers cible — celles dont le vecteur est proche du centre, donc proches
de tout. C'est le piège classique et il est silencieux.

---

## 5. Le vecteur utilisateur

C'est ici que le système devient un produit.

### 5.1 L'utilisateur n'est pas un point

L'erreur naturelle serait de résumer quelqu'un par le centre de gravité de ses fives. Ça perd
l'essentiel : **ce qui caractérise un goût, c'est autant sa constance que sa position**.

Prenons un membre dont les 5 séries de sa vie donnent :

| | Luminosité | Humour | Étrangeté |
|---|---|---|---|
| série 1 | 2 | 3 | 8 |
| série 2 | 3 | 9 | 9 |
| série 3 | 2 | 2 | 7 |
| série 4 | 1 | 8 | 9 |
| série 5 | 3 | 4 | 8 |
| **moyenne μ** | **2,2** | **5,2** | **8,2** |
| **écart-type σ** | **0,8** | **3,1** | **0,8** |

Lecture :

- **Luminosité** : jamais au-dessus de 3 → critère **fort**, il veut du sombre
- **Humour** : de 2 à 9 → **indifférent**, ce n'est pas un critère pour lui
- **Étrangeté** : constamment haut → critère **fort**, il veut du singulier

Le profil n'est donc pas « le milieu de ses 5 séries » mais **une position et une exigence par
axe** : 12 paramètres pour 6 axes.

Et c'est directement affichable :

> *« Vous aimez les univers sombres et singuliers. Le ton, lui, vous est égal. »*

### 5.2 Le calcul

**Position** — moyenne pondérée par le rang dans le top (la 1ʳᵉ place pèse plus que la 5ᵉ) :

```
μ_a = Σ_i (w_i · x_ia) / Σ_i w_i        avec  w = [1.5, 1.25, 1.0, 1.0, 1.0]
```

**Tolérance** — l'écart-type est très bruité sur 5 points. On le **contracte vers l'écart-type
de la population** :

```
σ²_a = (n · s²_a + k · σ²_pop,a) / (n + k)        avec  n = 5,  k ≈ 5
```

Concrètement : avec 5 fives on est à mi-chemin entre « ce que dit cet utilisateur » et « ce que
fait la population ». À mesure que les fives et les swipes s'accumulent, `n` grandit et
l'estimation devient propre. Sans cette contraction, un utilisateur dont les 5 séries ont par
hasard le même humour serait déclaré « exigeant sur l'humour » à tort.

**Poids par axe** — l'inverse de la tolérance, normalisé :

```
w_a = (1 / (σ²_a + ε)) / Σ_b (1 / (σ²_b + ε))
```

Un axe resserré pèse lourd, un axe dispersé disparaît du calcul. C'est exactement le
comportement voulu.

### 5.3 Le score d'une suggestion

```
score(œuvre) = − Σ_a  w_a · (x_a − μ_a)²
```

Une distance euclidienne pondérée, rien de plus. Un écart sur un axe à forte exigence est
lourdement pénalisé, un écart sur un axe indifférent est ignoré.

Pour l'utilisateur ci-dessus : une série lumineuse est éliminée même si elle est excellente ;
une série sombre et singulière remonte, qu'elle soit drôle ou non.

**Ce score n'est pas le classement final.** Il produit une zone de goût ; à l'intérieur, c'est
le graphe Neo4j qui départage. Le vecteur dit *où chercher*, le graphe dit *quoi prendre*.
Le vecteur ne prend la main seul que dans les deux cas où le graphe est muet : le nouvel
inscrit, et le passage d'un univers à l'autre.

### 5.4 L'apprentissage par le swipe

Les 5 fives donnent une initialisation. Les swipes affinent.

Modèle : pour chaque axe, on calcule l'écart normalisé à la position de l'utilisateur, puis on
apprend une régression logistique en ligne.

```
z_a    = (x_a − μ_a) / σ_pop,a
logit  = b + Σ_a ( θ_a · z_a  +  φ_a · z_a² )
P(like) = 1 / (1 + e^−logit)
```

- **θ_a** capte une préférence orientée — « j'aime **plus** sombre que mon centre actuel »
- **φ_a**, négatif, capte l'exigence — « je veux rester **près** de mon centre sur cet axe »

13 paramètres (6 × 2 + biais), initialisés depuis les fives, régularisés en L2 vers cette
initialisation. Apprenables en 30 à 50 swipes. Et **θ et φ se relisent en français**, ce qui
garde l'explication disponible à tout moment.

Les quatre réponses du swipe ne portent pas la même information et ne doivent pas être
fusionnées :

| Réponse | Signal | Usage |
|---|---|---|
| **J'ai vu & aimé** | goût confirmé | poids fort, alimente aussi le graphe |
| **Je veux voir** | intention | poids moyen sur le goût, entre en wishlist |
| **J'aime pas** | rejet | poids fort, négatif |
| **Passer** | ni l'un ni l'autre | poids nul sur le goût — masque l'œuvre 30 jours |

### 5.5 Le swipe comme instrument de mesure

Pendant les **15 à 20 premiers swipes**, ne pas montrer la meilleure suggestion : montrer
celle qui **réduit le plus l'incertitude**.

Heuristique simple et suffisante : repérer l'axe de plus grande incertitude, et proposer deux
œuvres qui s'opposent fortement sur cet axe tout en étant proches sur tous les autres. Chaque
swipe devient alors une mesure propre au lieu d'un signal confondu.

Un profil à 6 dimensions se cerne en une vingtaine de swipes bien choisis, contre des
centaines de swipes aléatoires. Et l'onboarding devient un jeu plutôt qu'un formulaire.

Ensuite, bascule en mode exploitation : on montre les meilleures suggestions.

---

## 6. Le cross-média

### 6.1 Deux pièges

**Comparer en absolu.** Traité en §4.2 — normaliser par univers, sinon on remonte les œuvres
les plus moyennes de l'univers cible.

**Supposer que les axes s'alignent.** Rien ne garantit qu'une intensité de 8 en musique
corresponde à une intensité de 8 en littérature.

### 6.2 L'actif qui résout le second

Les membres de la V1 ayant rempli des fives dans **plusieurs univers** fournissent des
milliers de paires observées : « ceux qui aiment ces 5 séries aiment ces 5 livres ». C'est
exactement la supervision qu'il faut pour **apprendre** la matrice de passage entre univers
au lieu de la postuler.

C'est probablement l'actif le plus précieux de la V1 — bien avant le code.

Même mécanisme pour l'étrangeté relative (§2.2) : la population de référence d'un utilisateur
se déduit de son historique, pas d'un paramètre déclaré.

---

## 7. Décisions ouvertes

| # | Question | Comment trancher |
|---|---|---|
| 1 | ⚠️ **Exigence et Étrangeté fusionnent-elles ?** Si oui → un seul axe **Radicalité** (`1 = immédiat et balisé` → `10 = exigeant et singulier`), et on descend à 5 axes | matrice de corrélation sur 300 œuvres notées |
| 2 | Combien d'ancres par axe, et faut-il un jeu par aire culturelle ? | fidélité test-retest par aire |
| 3 | La valeur de `k` dans la contraction (§5.2) | validation croisée sur la reconstitution des fives |
| 4 | Le seuil de confiance d'entrée en production | courbe précision/couverture |
| 5 | Modèle distillé : quel encodeur pour la traîne ? | après avoir noté la tête |

**La question 1 est bloquante pour le reste** : elle change le nombre d'axes, donc le schéma,
les ancres et le coût de notation. Elle se répond en quelques jours.

---

## 8. Comment valider tout ça

Une seule métrique décide, et elle est mesurable **dès aujourd'hui sur la base V1** :

> **Reconstitution des fives** — on masque un des 5 éléments d'un membre. Le système le
> remonte-t-il dans le top 50 ?

Deux métriques de contrôle :

- **Pouvoir prédictif par axe** — chaque axe prédit-il les swipes mieux que le hasard ? Ceux
  qui ne prédisent rien, on les supprime. C'est ainsi qu'on passe de 12 axes candidats aux 6
  qui servent.
- **Cohérence de notation** — §3.5.

---

## 9. La première étape

1. Écrire les **12 axes candidats** avec leurs ancres par univers (barème `v1`).
2. Choisir **300 œuvres** couvrant les 5 univers et tout le spectre de popularité.
3. Les noter, mesurer les corrélations, **trancher la question 1**.
4. Valider contre `similar_tmdb_raw` et contre la reconstitution des fives V1.

Si ça tient sur 300 œuvres, ça tiendra sur 300 000. Sinon, on l'aura appris avant d'avoir
écrit le produit.
