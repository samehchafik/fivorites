# Empreinte culturelle : analyse d'impact du changement de référentiel

Note d'impact, rédigée le 2026-08-10, en réponse à la décision de remplacer les
six axes de goût (`luminosite`, `intensite`, `humour`, `exigence`, `etrangete`,
`sensoriel`) par les six dimensions émotionnelles du programme de R&D :
**Joie, Rêve, Tristesse, Peur, Réflexion, Action**.

Source de référence : *Le Programme de R&D — Fivorites.com*, §4.5.1.5
« Empreinte culturelle : un nouveau référentiel », et Lot 11 (25,5 jours/homme).

---

## 1. Ce que demande le programme de R&D

Reformulé fidèlement depuis le §4.5.1.5 :

- un référentiel **à 6 dimensions**, chacune correspondant à **une émotion**,
  construit à partir des « émotions fondamentales » et adapté aux objets
  culturels ;
- il classe **les objets *et* les membres** dans le même espace ;
- chaque objet est positionné **à froid**, en utilisant d'abord **les catégories
  (genres)** qui lui sont associées — puis « il sera ensuite possible d'ajuster
  les coordonnées de chaque objet » ;
- les distances sont **de type cosine** ;
- l'empreinte d'un membre se déduit de la liste des objets qui lui sont associés ;
- le score qui en résulte doit **élargir le périmètre** des recommandations et
  fonctionner **d'abord en concurrence** du score de graphe, puis
  éventuellement en combinaison.

Le schéma du document rattache les genres aux pôles ainsi :

| Pôle | Genres rattachés |
|---|---|
| **Joie** | Comédie, Comique, Humour |
| **Rêve** | SF, Fantastique, Conte |
| **Réflexion** | Documentaire, Essai, Philosophie |
| **Tristesse** | Drame, Romance, Catastrophe |
| **Peur** | Épouvante, Horreur, Catastrophe |
| **Action** | Action, Aventure, Catastrophe |

*(« Catastrophe » apparaît sur trois pôles, « Documentaire » entre Rêve et
Réflexion : le schéma est un continuum, pas une partition. C'est voulu, et
c'est un point de conception à formaliser — voir §7.)*

---

## 2. Le point qui commande tout : ce n'est pas le même type d'axe

C'est la conclusion principale de cette analyse, et tout le reste en découle.

**Les six axes actuels sont des axes bipolaires.** Une question, une échelle
ordonnée, un nombre : `luminosite = 2` veut dire *sombre*, `= 9` veut dire
*lumineux*. Les deux bouts sont des valeurs opposées d'une même grandeur, et
la position au milieu a un sens.

**Les six dimensions de l'empreinte culturelle sont des composantes d'un
mélange.** Joie, Peur, Action ne sont pas les bouts d'une échelle : ce sont six
directions. Une œuvre n'a pas *une position* sur Joie, elle *contient* une
certaine quantité de Joie. `joie = 2` ne veut pas dire « le contraire de la
joie », mais « peu de joie » — ce qui est une information de nature différente.

| | Axes de goût (actuel) | Empreinte culturelle (cible) |
|---|---|---|
| Nature | positions bipolaires | composantes d'un mélange |
| Ce que dit 1 | l'autre pôle | absence de cette composante |
| Le milieu | valeur pleine de sens | valeur peu informative |
| Distance naturelle | euclidienne pondérée | **cosine** (le PDF le dit) |
| Profil utilisateur | position **+ tolérance** par axe | moyenne des mélanges aimés |
| Lisible en français | « vous aimez le sombre » | « vous aimez la peur et l'action » |

**Conséquence directe** : ce n'est pas un renommage. Tout le §5 de
[`v2-notation-axes.md`](v2-notation-axes.md) — le vecteur utilisateur, la
contraction de la variance, la pondération par l'inverse de la tolérance, le
score de suggestion — est bâti sur l'hypothèse « position + tolérance » et **ne
se transpose pas tel quel**. Voir §5 ci-dessous.

---

## 3. Bonne nouvelle : l'impact sur le code est faible

Le système a été écrit pour que la liste des axes soit une donnée, et une
grande partie du reste n'est encore que de la spécification.

| Composant | Impact | Pourquoi |
|---|---|---|
| `notation.score` | **aucun** | une ligne par (œuvre, axe) — pas de colonne par axe |
| `notation.weights`, `embedding`, `training_run`, `training_weights` | **aucun** | `axe` est une donnée, pas un schéma |
| `routes/training.py` | **aucun** | tout lit `rubric["axes"]` et boucle dessus |
| `weights.py` | **commentaires**, sauf §6 | la ridge marche sur n'importe quel axe numérique |
| `dossier.py` | **aucun** | `GENRES` et `KEYWORDS` sont déjà dans le dossier |
| `embed.py` | **aucun** | l'encodeur ne connaît pas les axes |
| `front/types.ts` | **aucun** | les scores sont un `Record<string, number>` |
| `AxisVector.tsx` | **6 libellés**, + visualisation (§6) | les axes inconnus s'affichent déjà |
| Tests | fixtures à renommer | ils nomment `luminosite` en dur |
| Migration | **1 fichier neuf** | le nouveau référentiel |

**Et surtout : la distance et le profil utilisateur ne sont pas encore
implémentés.** Une recherche sur `cosine`, `distance`, `user_vector` dans
`admin/src` et `front/src` ne renvoie rien. Le §5 du doc est un plan, pas du
code. **Changer de référentiel maintenant coûte donc infiniment moins cher que
dans six mois** — c'est l'argument le plus fort en faveur de faire la bascule
tout de suite.

---

## 4. Mauvaise nouvelle : le capital de calibration est perdu

Ce qui disparaît n'est pas du code, c'est du **travail de réglage** :

- **521 œuvres notées** en barème v2 cessent de compter (l'entraînement filtre
  sur `rubric_version`). Renoter coûte ~2 $ et quelques heures — négligeable.
- **Ce qui coûte vraiment** : la calibration v1 → v2. Les jeux d'ancres, la
  règle de preuve de `sensoriel`, la distinction intensité/rythme, la ligne
  « la télévision courante vit en zone 4-6 » — chaque correction venait d'un
  écart mesuré entre GPT et Claude. L'écart moyen est passé de **1,32 à 0,96**
  par ce travail. Sur les nouvelles dimensions, il repart de zéro.
- Les mesures accumulées (courbe de volume, comparaison d'encodeurs,
  diagnostic visuel, pente de recalibration) restent **méthodologiquement**
  valides mais leurs **valeurs** sont à refaire.

Ce n'est pas un argument contre la bascule — c'est le prix à provisionner, et
il se paie une fois. La méthode, elle, est intacte : voir
[`mission-nouveaux-axes.md`](mission-nouveaux-axes.md), qui reste entièrement
applicable (règles d'ancrage, ancres disjointes, sections porteuses de signal,
ne jamais changer deux choses à la fois).

---

## 5. Ce qu'il faut repenser, et pas seulement réécrire

### 5.1 Le profil utilisateur — la partie la plus touchée

Le mécanisme actuel dit : *ce qui caractérise un goût, c'est autant sa
constance que sa position*. Un axe où les cinq fives d'un membre sont
resserrés est un critère fort ; un axe dispersé est ignoré. D'où 12 paramètres
(position μ + tolérance σ par axe) et une pondération par l'inverse de la
variance.

**Sur des composantes, ce raisonnement s'inverse.** Si les cinq œuvres
préférées d'un membre contiennent toutes beaucoup de Peur, ce n'est pas « une
faible variance sur l'axe peur », c'est simplement « il aime la peur ». La
moyenne des mélanges **est** le profil ; la variance ne porte plus le même
sens.

Il reste vrai qu'une composante quasi absente partout (« il ne regarde jamais
rien de drôle ») est une information forte — mais c'est la **moyenne basse**
qui la porte, pas la faible dispersion.

→ **§5.1, §5.2 et §5.3 de [`v2-notation-axes.md`](v2-notation-axes.md) sont à
réécrire, pas à retoucher.** La formule de score `− Σ w·(x−μ)²` devient une
similarité cosine entre le profil du membre et l'empreinte de l'œuvre.

### 5.2 La contraction vers la moyenne devient un danger de premier ordre

Point technique non évident, et c'est le risque le plus sérieux de la bascule.

La régression ridge contracte ses prédictions vers la moyenne : on a mesuré une
pente de **0,49 à 0,68** sur les prédictions hors-pli — soit près de la moitié
de l'amplitude perdue. En distance euclidienne pondérée, cela **dégrade** le
classement. **En distance cosine, cela peut l'annuler** : cosine ne regarde que
la *direction* du vecteur. Si toutes les prédictions convergent vers le profil
moyen du catalogue, tous les vecteurs pointent à peu près dans la même
direction, toutes les similarités valent ~0,95, et le système ne discrimine
plus rien — sans qu'aucune métrique d'erreur ne le signale.

→ La **recalibration** déjà implémentée dans `weights.py` passe de
« souhaitable » à **indispensable**. Et il faut lui ajouter un contrôle
explicite : *la dispersion des empreintes prédites est-elle comparable à celle
des empreintes notées ?* Une erreur moyenne faible avec une dispersion écrasée
est le pire des cas, et c'est celui vers lequel une ridge tend naturellement.

### 5.3 Ce qui n'est **pas** retenu du PDF : l'amorçage par les genres

Le PDF propose de positionner chaque objet **à froid depuis ses genres**, puis
d'ajuster les coordonnées. **Cette partie n'est pas reprise.** La notation reste
faite par le juge LLM, exactement comme aujourd'hui : même dossier, même appel,
même table, même contre-juge, même régression. **On change le barème qu'il
applique, et rien d'autre.**

C'est le bon choix, et on peut le justifier par une mesure qu'on a faite sans le
vouloir. Le premier encodeur retenu (`all-MiniLM-L6-v2`) avait une fenêtre de
128 tokens : il ne lisait que le titre, les faits, **les genres** et une partie
des mots-clés — rien du synopsis, des résumés de saison, des épisodes ni de
Wikipédia. La régression prédisait donc les axes essentiellement à partir des
genres, et **elle plafonnait**. C'est consigné dans
`admin/src/fiv_admin/embed.py`. Les genres seuls ne séparent pas les œuvres :
deux séries du même genre auraient reçu la même empreinte, ce que le vecteur
existe précisément pour éviter — « un axe n'est pas une catégorie, c'est une
mesure ».

**Mais le risque ne disparaît pas : il se déplace dans le prompt.** Le juge lit
la section `GENRES` du dossier. Si les définitions des six dimensions nomment
les genres qui les portent — « Joie : comédie, comique, humour » — le juge se
contentera de recopier l'étiquette, et l'empreinte redeviendra une taxonomie
déguisée par un autre chemin.

→ **Les définitions doivent décrire l'émotion, jamais le genre qui la porte
d'habitude.** C'est exactement la règle qui protégeait déjà `humour` (« ce n'est
pas l'étiquette de genre comédie ») ; elle devient centrale ici, puisque le
référentiel du PDF est justement présenté par ses genres. Les genres du schéma
servent à *nous* faire comprendre le référentiel — ils ne doivent pas entrer
dans la consigne du juge.

### 5.4 Normalisation : la question de conception à trancher

Deux options, et elle décide de la suite.

| | **A. Six notes indépendantes 0-10** | **B. Composition normalisée (somme = 100)** |
|---|---|---|
| Notation LLM | naturelle, identique à aujourd'hui | le juge doit répartir un budget — nettement plus dur |
| Régression | ridge actuelle, inchangée | régression contrainte (≥ 0, somme fixe) — à écrire |
| Distance cosine | fonctionne (elle normalise de fait) | fonctionne |
| Intensité globale | conservée (une œuvre peut être forte partout) | perdue par construction |
| Coût d'implémentation | nul | réel |

**Recommandation : option A.** Elle préserve la machinerie entière, elle est
plus facile à noter et à ancrer, et la distance cosine imposée par le PDF
normalise de toute façon les vecteurs au moment de la comparaison. Le seul
avantage de B — la comparabilité directe des proportions — est obtenu
gratuitement par le cosine.

Nuance à garder à l'esprit : avec A, deux œuvres de même « couleur » mais
d'intensité différente auront une similarité cosine de 1. Si l'on veut
distinguer *un peu de peur* de *beaucoup de peur*, il faudra réintroduire la
norme comme critère secondaire — c'est faisable, mais c'est une décision à
prendre consciemment plutôt qu'à découvrir.

---

## 6. Le front

`AxisVector.tsx` affiche déjà tout axe inconnu : rien ne casse. Mais deux choix
de conception du composant deviennent discutables.

1. **La visualisation.** Six barres verticales conviennent à des positions
   indépendantes. Pour un mélange, un **radar** (ou un empilement) montre la
   *forme* de l'empreinte, qui est précisément ce que le cosine compare.
2. **La couleur.** Le commentaire du composant justifie la teinte unique ainsi :
   *« une couleur par axe suggérerait un classement qui n'existe pas »*. C'était
   juste pour des axes de goût — « humour élevé » n'est ni mieux ni moins bien.
   Avec des émotions nommées, **une couleur par émotion devient au contraire
   naturelle et lisible** (Joie/jaune, Peur/violet sombre, Action/rouge…), et
   l'empreinte devient reconnaissable d'un coup d'œil sur une carte.

C'est aussi un gain produit direct : « Joie 8 / Peur 2 / Action 6 » se lit sans
apprentissage, là où « Étrangeté 7 » demandait une explication.

---

## 7. Le seul vrai travail : écrire le barème

Puisque le pipeline ne change pas, **tout le travail tient dans le texte du
prompt** — six définitions et leurs ancres. Les règles qui s'y appliquent sont
celles déjà payées en v1 → v2 (détail dans
[`mission-nouveaux-axes.md`](mission-nouveaux-axes.md) §5) :

1. **Décrire l'émotion, jamais le genre** (§5.3) — la règle la plus importante
   ici, puisque le référentiel du PDF est présenté par ses genres.
2. **Trois à cinq ancres par dimension**, couvrant toute la portée : une près de
   1, une près de 10, au moins une au milieu.
3. **Aucune œuvre ne sert d'ancre à deux dimensions** — c'est la leçon la plus
   coûteuse de la v2, où *Twin Peaks* ancrait `exigence` **et** `etrangete`,
   soit les deux axes dont on cherchait justement à savoir s'ils fusionnaient.
4. **Une ligne « ce n'est pas »** par dimension : c'est là que les notations
   dérapent, et c'est la ligne qui fait le plus de travail.
5. **La ligne de calibration doit changer de nature.** En v2 elle disait « la
   télévision courante vit en zone 4-6 ». C'est vrai de positions, **faux de
   composantes** : une œuvre porte typiquement une ou deux émotions dominantes
   et peu du reste. La nouvelle consigne doit dire l'inverse — *ne pas répartir
   les six notes uniformément ; l'asymétrie est le signal.*
6. **La règle de preuve.** Un synopsis dit ce qui se passe, pas ce qu'on
   ressent. `Peur` et `Joie` y sont particulièrement exposées — c'est la même
   difficulté que `humour`, resté bloqué à 1,25. Prévoir `null` plutôt que la
   déduction par le genre.
7. **Le nom du référentiel.** `v3` prolonge la lignée, mais ce n'est pas une
   révision du même barème : c'est un autre référentiel. `empreinte-v1` rend la
   rupture lisible dans la base et évite qu'on compare par erreur un écart v2 à
   un écart v3.

Une proposition complète de barème est donnée en §11.

---

## 8. Ce que la bascule fait gagner

Pour être complet, et parce que ces gains sont réels :

- **Le cross-média devient natif.** Deux des six axes actuels avaient dû être
  écartés du socle faute de tenir sur tous les univers. Joie, Tristesse, Peur,
  Rêve, Réflexion, Action tiennent en musique, en littérature et en BD sans
  reformulation. C'est exactement ce que le socle devait faire.
- **L'alignement avec le programme de R&D** : le Lot 11 prévoit l'intégration
  des empreintes dans Neo4j et un score utilisable par le moteur FIVO existant.
  Les six axes de goût, eux, n'avaient pas de point d'entrée dans le moteur
  actuel.
- **La lisibilité produit** (voir §6).
- **Les membres entrent dans le même espace que les objets**, ce qui était
  l'objectif du référentiel et que le dispositif actuel n'adressait pas encore.

---

## 9. Plan de bascule

1. **Arrêter le barème** — les six définitions et leurs ancres (proposition en
   §11). *C'est la seule étape qui demande une décision ; tout le reste est
   mécanique.*
2. **Écrire la migration** `009_empreinte_v1.sql` : prompt complet à six
   dimensions, `axes` en jsonb, `note` expliquant la rupture. **Ne pas toucher
   à v1 ni v2** — le schéma est append-only, elles restent lisibles et
   comparables pour rien.
3. **Noter 30 à 50 œuvres** avec le juge, examiner à la main dans l'atelier,
   contre-noter avec Claude, corriger les définitions qui divergent. Itérer ici
   coûte quelques centimes ; itérer après 500 œuvres coûte une version.
4. **Vérifier que l'empreinte ne recopie pas les genres.** Le contrôle le plus
   utile du lot : prendre deux séries de mêmes genres et de tons opposés — par
   exemple *Brooklyn Nine-Nine* et *The Shield*, toutes deux « policier » — et
   regarder si leurs empreintes diffèrent. Si elles se ressemblent, la consigne
   parle encore de genre (§5.3).
5. **Renoter le lot complet** (521 œuvres, ~2 $), puis `training poids`.
6. **Contrôler la dispersion** des empreintes prédites (§5.2), pas seulement
   l'erreur moyenne.
7. **Réécrire** §2, §3.1, §5 et §7 de [`v2-notation-axes.md`](v2-notation-axes.md).
8. **Front** : libellés, couleurs, radar.

Le PDF prévoyait 25,5 jours/homme pour le Lot 11 sur la plate-forme V1. Sur la
V2, l'essentiel est déjà payé — le pipeline de notation, le stockage versionné,
la régression et l'atelier existent. Ce qui reste tient dans l'étape 1
(le barème) et l'étape 8 (l'affichage).

---

## 10. En un mot

Le changement est **peu coûteux en code et profond en conception**. Il tombe au
bon moment : la distance et le profil utilisateur n'étant pas encore écrits,
c'est le dernier instant où la bascule ne casse rien.

Les deux pièges à ne pas manquer :

- **laisser les genres entrer dans la consigne du juge**, et transformer une
  mesure en taxonomie déguisée. Le référentiel du PDF se présente par ses genres
  (« Joie : comédie, comique, humour ») ; les définitions envoyées au juge, elles,
  ne doivent parler que de l'émotion (§5.3) ;
- **laisser la ridge contracter vers la moyenne**, ce qui en distance cosine
  annule la discrimination sans qu'aucune métrique d'erreur ne le montre (§5.2).

---

## 11. Proposition de barème `empreinte-v1`

Brouillon à discuter, appliquant les sept règles du §7. Rédigé en anglais,
comme les barèmes v1 et v2 — la langue de notation décidée le 2026-08-07.

### 11.1 L'en-tête

> You are a cultural-work rater. Read the dossier about a TV series and score
> it on six emotional dimensions, each from 1 to 10. These dimensions are
> **not opposites on a scale** — they are components of a mixture. A score of 1
> means the work carries almost none of that emotion; 10 means it is a dominant
> emotional register of the work.
>
> **Most works carry one or two dominant emotions and little of the rest. Do
> not spread the six scores evenly — the asymmetry is the signal.** A comedy
> scoring high on Joy should score low on Fear. A work scoring 6 or above on
> four dimensions is almost certainly mis-scored.
>
> Anchor works define each scale. Place the series relative to them.
>
> **Score the emotion the work delivers, never its genre label.** Genres are
> listed in the dossier for context only; two works of the same genre routinely
> have very different emotional fingerprints, and telling them apart is the
> entire purpose of this exercise.
>
> For each dimension give an integer 1-10 and a confidence 0.0-1.0. A synopsis
> describes what happens, not what it feels like — if the dossier gives no
> reliable basis for a dimension, return null with low confidence rather than
> inferring it from the genre. A missing score is better than an invented one.

### 11.2 Les six dimensions

| | Dimension | 1 | 10 |
|---|---|---|---|
| 1 | **`joie`** — Joy | aucune légèreté, aucun plaisir | euphorique, réjouissant |
| 2 | **`reve`** — Wonder | strictement le monde réel | pur imaginaire, merveilleux |
| 3 | **`tristesse`** — Sorrow | aucun chagrin | déchirant, endeuillé |
| 4 | **`peur`** — Fear | aucune angoisse | terrifiant, oppressant |
| 5 | **`reflexion`** — Thought | ne demande rien à l'esprit | interroge le monde en continu |
| 6 | **`action`** — Action | immobile, verbal | physique, en mouvement constant |

**`joie` — Joy.** *How much lightness, pleasure, warmth does the work deliver?*
**NOT** the comedy genre, and **NOT** a happy ending. A bleak comedy scores low;
a serious drama with real warmth between its characters scores mid. Score the
lift the work gives, not what it is filed under.
*Anchors : Chernobyl = 1, Mad Men = 4, Modern Family = 8, Parks and Recreation = 10.*

**`reve` — Wonder.** *How far does the work depart from the real world?*
**NOT** the budget or the special effects. A low-budget fairy tale scores high;
an expensive, meticulously realistic war series scores low. Score the presence
of the imaginary — the marvellous, the impossible, the dreamlike.
*Anchors : The Wire = 1, The Crown = 2, Doctor Who = 8, The Sandman = 10.*

**`tristesse` — Sorrow.** *How much grief, loss, melancholy does the work carry?*
**NOT** darkness or hopelessness — a sorrowful work can be tender and
consoling. **NOT** the quality of its drama. Score the weight of sadness the
viewer actually carries away.
*Anchors : Seinfeld = 1, Breaking Bad = 6, This Is Us = 9, Six Feet Under = 10.*

**`peur` — Fear.** *How much dread, anxiety, threat does the work generate?*
**NOT** violence and **NOT** gore: a very violent series with no sense of dread
scores low, and a quiet series where something feels deeply wrong scores high.
Score the anxiety, not the body count.
*Anchors : Downton Abbey = 1, Stranger Things = 6, The Walking Dead = 8, The Haunting of Hill House = 10.*

**`reflexion` — Thought.** *Does the work make you think about something beyond
its own plot?* **NOT** difficulty — that is a separate matter. An accessible
documentary scores high; a dense, twisty thriller that raises no question scores
low. Score whether the work is *about* something.
*Anchors : NCIS = 1, Grey's Anatomy = 3, Westworld = 8, Black Mirror = 10.*

**`action` — Action.** *How much physical movement, confrontation and bodily
stakes does the work contain?* **NOT** editing pace: a fast-talking series with
people in rooms scores low. Score what the bodies do.
*Anchors : Friends = 1, Sherlock = 4, Game of Thrones = 8, 24 = 10.*

### 11.3 Vérifications appliquées à cette proposition

- **24 œuvres-ancres, toutes distinctes** — aucune ne sert deux dimensions
  (§7.3). C'est la contrainte qui a le plus guidé les choix.
- **Portée couverte** partout : chaque dimension a une ancre à 1, une haute et
  une à 10, et une intermédiaire — sauf `reve` dont l'intermédiaire est à 2, à
  compléter si le premier lot montre un trou dans le milieu.
- **Aucune définition ne cite un nom de genre**, sauf pour le nier
  explicitement (« NOT the comedy genre »).
- **Les six « ce n'est pas »** visent les confusions les plus probables :
  joie/comédie, rêve/budget, tristesse/noirceur, peur/violence,
  réflexion/difficulté, action/rythme.
- `tristesse` **ne reprend pas** `luminosite` : l'une mesure le chagrin porté,
  l'autre mesurait le regard sur le monde. Un récit peut être très triste et
  peu désespéré — c'est la distinction que la ligne « NOT darkness » protège.

### 11.4 Ce qui reste à décider

- Les six ancres à 10 sont des séries anglo-saxonnes prestigieuses. C'est le
  défaut connu de la v2, et il pèse surtout sur `joie` — ce qui est drôle voyage
  mal d'une culture à l'autre. À revoir si le catalogue s'ouvre.
- `reflexion` et `reve` peuvent se recouvrir sur la SF d'idées (*Black Mirror*,
  *Westworld* sont tous deux les deux). C'est la paire à surveiller dans la
  matrice de corrélation, comme `exigence` × `etrangete` l'était en v2.
