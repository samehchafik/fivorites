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

### 5.3 Le positionnement à froid par les genres — et ce qu'on en sait déjà

Le PDF propose de positionner chaque objet **à froid depuis ses genres**, puis
d'ajuster. C'est séduisant : c'est **gratuit, instantané, et applicable
immédiatement aux 100 millions d'objets** de la base search, toutes familles
confondues. Aucun appel LLM, aucun budget.

Mais nous avons déjà mesuré, par accident, ce que vaut ce régime. Le premier
encodeur retenu (`all-MiniLM-L6-v2`) avait une fenêtre de 128 tokens : il ne
lisait que le titre, les faits, **les genres** et une partie des mots-clés —
rien du synopsis, des résumés de saison, des épisodes ni de Wikipédia. La
régression prédisait donc les axes essentiellement à partir des genres, et
**elle plafonnait**. C'est consigné dans `admin/src/fiv_admin/embed.py`.

Ce n'est pas un argument contre l'empreinte culturelle : c'est un argument pour
prendre le PDF au mot sur le mot **« d'abord »**. Le positionnement par genres
est un **amorçage**, pas un résultat.

Le risque à nommer explicitement : **deux séries du même genre auront la même
empreinte à froid.** Or c'est exactement ce que le vecteur de goût existe pour
éviter — la première phrase de la spécification actuelle est « un axe n'est pas
une catégorie, c'est une mesure ». Si l'on s'arrête à l'amorçage, on remplace
une mesure par une taxonomie déguisée, et le pouvoir de discrimination
intra-genre s'effondre.

→ **La couche de notation LLM garde donc toute sa raison d'être** : elle
devient l'étage d'« ajustement des coordonnées » que le PDF prévoit. On ne jette
rien du dispositif — dossier, juge, contre-juge, ridge, recalibration : on
change le barème qu'il applique.

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

## 7. Points à formaliser avant d'écrire le barème

1. **Le rattachement genre → pôles.** Le schéma du PDF est un continuum où
   « Catastrophe » nourrit Tristesse, Peur *et* Action. Il faut une table de
   correspondance explicite, avec des **poids** (ex. Catastrophe → Peur 0,4 /
   Action 0,4 / Tristesse 0,2), sinon chaque implémentation l'interprétera
   autrement.
2. **La couverture des genres réels.** Les genres TMDB (`Sci-Fi & Fantasy`,
   `Kids`, `Reality`, `Talk`, `News`, `Soap`, `War & Politics`, `Western`…) ne
   recouvrent pas la liste du schéma. Il faut décider où tombent `Reality`,
   `Talk`, `News`, `Kids` — ou admettre qu'ils n'ont pas d'empreinte à froid.
3. **`Documentaire` est placé entre Rêve et Réflexion** dans le schéma, ce qui
   surprend. À confirmer : c'est probablement Réflexion, avec le documentaire
   de nature/espace tirant vers Rêve.
4. **Les ancres.** Six œuvres-repères par dimension, couvrant toute la portée,
   **sans qu'aucune œuvre serve d'ancre à deux dimensions** — c'est la leçon la
   plus coûteuse de la v2 (voir [`mission-nouveaux-axes.md`](mission-nouveaux-axes.md) §5.3).
5. **La règle de preuve.** `sensoriel` avait besoin d'indices explicites sous
   peine de deviner. `Peur` et `Joie` sont dans le même cas : un synopsis dit ce
   qui se passe, pas ce qu'on ressent. Prévoir `null` plutôt que la déduction
   par le genre — sinon l'empreinte n'est qu'une paraphrase des genres, ce qui
   nous ramène au §5.3.
6. **Le nom du référentiel.** `v3` prolonge la lignée, mais ce n'est pas une
   révision du même barème : c'est un autre référentiel. Proposer
   `empreinte-v1` rend la rupture lisible dans la base et évite qu'on compare
   par erreur un écart v2 à un écart v3.

---

## 8. Ce que la bascule fait gagner

Pour être complet, et parce que ces gains sont réels :

- **Le cross-média devient natif.** Deux des six axes actuels avaient dû être
  écartés du socle faute de tenir sur tous les univers. Joie, Tristesse, Peur,
  Rêve, Réflexion, Action tiennent en musique, en littérature et en BD sans
  reformulation. C'est exactement ce que le socle devait faire.
- **La couverture froide est immédiate et gratuite** sur toute la base search,
  toutes familles — là où la notation LLM ne couvrira jamais que la tête.
- **L'alignement avec le programme de R&D** : le Lot 11 prévoit l'intégration
  des empreintes dans Neo4j et un score utilisable par le moteur FIVO existant.
  Les six axes de goût, eux, n'avaient pas de point d'entrée dans le moteur
  actuel.
- **La lisibilité produit** (voir §6).
- **Les membres entrent dans le même espace que les objets**, ce qui était
  l'objectif du référentiel et que le dispositif actuel n'adressait pas encore.

---

## 9. Plan de bascule

1. **Formaliser** les points du §7 — table genre → pôles pondérée, couverture
   TMDB, ancres disjointes, règle de preuve. *C'est la seule étape qui demande
   une décision ; tout le reste est mécanique.*
2. **Écrire la migration** `009_empreinte_v1.sql` : prompt complet à six
   dimensions, `axes` en jsonb, `note` expliquant la rupture. **Ne pas toucher
   à v1 ni v2** — le schéma est append-only, elles restent lisibles et
   comparables pour rien.
3. **Amorçage à froid** : une commande qui calcule l'empreinte de toute œuvre
   ayant des genres, sans LLM. Gratuit, et donne immédiatement une couverture
   de 100 %.
4. **Noter 30 à 50 œuvres** avec le juge, examiner à la main dans l'atelier,
   contre-noter, corriger les définitions. Itérer ici coûte quelques centimes ;
   itérer après 500 œuvres coûte une version.
5. **Mesurer l'écart amorçage-à-froid / notation LLM.** C'est le test décisif :
   si le LLM ne fait que confirmer les genres, l'étage de notation ne sert à
   rien sur ce référentiel et l'on économise tout le budget. S'il s'en écarte
   nettement, on tient la discrimination intra-genre que le §5.3 réclame.
6. **Renoter le lot complet** (521 œuvres, ~2 $), puis `training poids`.
7. **Contrôler la dispersion** des empreintes prédites (§5.2), pas seulement
   l'erreur moyenne.
8. **Réécrire** §2, §3.1, §5 et §7 de [`v2-notation-axes.md`](v2-notation-axes.md).
9. **Front** : libellés, couleurs, radar.

Le PDF prévoyait 25,5 jours/homme pour le Lot 11 sur la plate-forme V1. Sur la
V2, l'essentiel de cette charge est déjà payé — le pipeline de notation, le
stockage versionné, la régression et l'atelier existent. Ce qui reste est
l'étape 1 (conception) et les étapes 3 et 9 (amorçage, affichage).

---

## 10. En un mot

Le changement est **peu coûteux en code et profond en conception**. Il tombe au
bon moment : la distance et le profil utilisateur n'étant pas encore écrits,
c'est le dernier instant où la bascule ne casse rien.

Les deux pièges à ne pas manquer :

- **s'arrêter à l'amorçage par genres**, et transformer une mesure en
  taxonomie déguisée (§5.3) ;
- **laisser la ridge contracter vers la moyenne**, ce qui en distance cosine
  annule la discrimination sans qu'aucune métrique d'erreur ne le montre (§5.2).
