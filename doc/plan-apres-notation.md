# Après la notation : ce qui est acquis, ce qui peut encore monter

Écrit le 2026-08-15, à la clôture de la séquence encodeur. À lire après
[`etat-des-lieux-notation.md`](etat-des-lieux-notation.md), qui raconte comment
on est arrivé là ; celui-ci dit quoi faire ensuite, dans quel ordre, et surtout
ce qu'il ne faut **plus** essayer.

## 1. Le verdict : est-ce satisfaisant ?

Oui, et voici l'étalon pour en juger. L'erreur du système se compare à deux
bornes :

| | MAE |
|---|---|
| le juge contre lui-même (GPT re-noté deux fois sur le même dossier) | 0,37 |
| **la régression sur une œuvre jamais vue** | **0,84** |
| deviner la moyenne du catalogue partout | ~1,8 |

Sur une échelle de 1 à 10, la traîne jamais jugée est estimée à ±0,84 par axe
en moyenne — et les ~2 300 œuvres de tête portent la note **du juge lui-même**,
exacte, car la régression ne sert que ce qui n'a pas été jugé. Pour un système
de recommandation, où ce sont les rangs et les proximités qui comptent plus que
les valeurs absolues, c'est un socle sain. Les deux pires cas connus (Game of
Thrones −2,2 en tristesse, House +1,6 en peur) sont cartographiés, compris, et
couverts par leurs vraies notes.

Ce qui serait *insatisfaisant*, ce n'est pas le niveau d'erreur : c'est de
dépenser encore pour le réduire là où il ne peut plus bouger. D'où ce plan.

## 2. Le plancher, décomposé

L'erreur de 0,84 se décompose en trois parts, et chacune a son levier — ou n'en
a pas :

1. **Le bruit du juge (~0,37).** GPT change d'avis de 0,37 en moyenne quand il
   re-note le même dossier. Ce bruit est DANS les cibles d'entraînement et dans
   la mesure elle-même. Réductible : noter deux fois et moyenner divise ce
   bruit par √2.
2. **Le mur sujet/ton.** Le texte décrit ce qui se passe, pas ce que ça fait.
   Deux visages mesurés : GoT lissée vers ses voisins de fantasy plus tièdes ;
   House poussée vers la peur par son vocabulaire de crise médicale. Seule la
   matière du dossier peut l'attaquer — ni le volume, ni le modèle, ni
   l'encodeur (tous mesurés).
3. **L'erreur d'estimation (~0,15 d'écart ajustement/validation).** Fond en
   racine du volume ; le prochain doublement achèterait ~0,01. Quasi épuisée.

## 3. Le plan, par ordre de rendement

### Phase 1 — Livrer, plutôt qu'améliorer (le vrai prochain chantier)

La notation n'existe pas pour elle-même : elle alimente une recommandation.
Le §5 de [`v2-notation-axes.md`](v2-notation-axes.md) décrit encore le vecteur
utilisateur en « position + tolérance », un raisonnement d'axes bipolaires.
Sur des composantes d'un mélange, la formule devient une **similarité
cosinus** — et le terrain est enfin prêt : les cosinus entre œuvres sont
passés de 0,90 (tout se ressemblait) à 0,72 avec le nouvel encodeur.

C'est le seul chantier dont le rendement se mesure en valeur produit, pas en
centièmes de MAE. Tout le reste de ce plan peut attendre qu'il soit fait.

### Phase 2 — Étendre la couverture juge (opérationnel, ~5 $)

Continuer `training note` par popularité jusqu'au **top ~5 000 par univers**,
par lots de 500, `training poids` après chaque lot (gratuit). Ce n'est plus de
l'entraînement : c'est remplacer une estimation à ±0,84 par une mesure exacte,
à 0,001 $ l'œuvre, sur les œuvres que les utilisateurs verront réellement.

Critère d'arrêt : quand le MAE ne bouge plus sur deux lots consécutifs, le
plateau de la régression est prouvé ; on continue alors pour la couverture
seule, et on s'arrête quand la popularité des œuvres notées rejoint le bruit.

### Phase 3 — Diviser le bruit du juge (~le prix de re-noter la tête)

Le plancher le plus dur n'est pas le modèle, c'est que la cible tremble.
Re-noter chaque œuvre de tête une seconde fois et **moyenner** les deux
verdicts : bruit divisé par √2 (0,37 → 0,26), cibles plus stables, MAE
mécaniquement meilleur — et surtout des empreintes de tête plus fiables.
`--rejouer` existe déjà ; il manque seulement la moyenne à la lecture, une
modification locale de la sélection « note courante ».

À ne faire qu'après la phase 2 : re-noter coûte le même prix que noter une
œuvre nouvelle, et une œuvre jamais vue vaut plus qu'une deuxième opinion.

### Phase 4 — Attaquer le mur sujet/ton (le seul pari restant)

La seule voie qui puisse faire mieux que ~0,8 sur la traîne. Deux pistes, à
**mesurer avant d'engager** :

- **Les critiques côté films.** L'impasse mesurée (2,6 % de couverture) était
  côté séries ; TMDB est bien plus fourni en critiques de films. À compter en
  une requête avant toute chose — c'est l'erreur « livrer avant de compter »
  qu'on ne refait pas.
- **Une ligne de ton écrite par le juge.** Au moment où il note, le juge
  connaît l'œuvre (c'est mesuré : il note Lucifer drôle sans que le dossier le
  dise). Lui demander une ligne de synthèse tonale, la stocker, et l'ajouter au
  dossier **encodé**. ⚠ Piège de taille : si les œuvres notées ont cette ligne
  et pas la traîne, l'entraînement et la prédiction ne lisent plus le même
  genre de texte — il faudrait la produire pour la traîne aussi (~0,0005 $
  l'œuvre en mini), ce qui en fait un vrai projet, pas une retouche.

### Phase 5 — Régime de croisière

- nouvelles œuvres au catalogue → elles passent par l'encodeur API
  automatiquement ; noter le top des nouveautés au fil de l'eau ;
- `videos-check` périodique (existe) ; `training poids` après chaque campagne
  de notes ;
- l'élève distillé est **branché** (décision du 2026-08-23 : la traîne se note
  en local, sans dépendance API). Le compose monte `./export` sur `/modeles`
  du conteneur admin, et la bascule tient en une ligne de `.env` :

  ```
  EMBEDDER=local:/modeles/eleve-distille
  ```

  Dans l'ordre, et le premier pas est obligatoire — les poids vivent dans
  l'espace de leur encodeur, `notation generer` refuse sans eux :

  ```bash
  docker compose run --rm -e EMBEDDER=local:/modeles/eleve-distille admin training poids
  docker compose run --rm admin notation devis        # doit dire « gratuit »
  docker compose run --rm -d admin notation generer
  ```

  À garder en tête : cet élève a été distillé sur processeur à 256 tokens, et
  il rend **0,937** de MAE là où l'encodeur d'API rend 0,853 — c'est l'écart
  qu'on accepte contre la gratuité et l'indépendance réseau. Une heure de GPU
  (~2 $) avec 1 024 tokens resserrerait cet écart ; le jour venu, re-distiller
  et rejouer `training poids` suffit, le reste de la chaîne ne bouge pas.

## 4. Ce qu'il ne faut PLUS essayer — la liste des leviers morts

Chaque ligne a coûté une mesure ; les refaire coûterait une deuxième fois.

| levier | verdict mesuré |
|---|---|
| volume pour le MAE | plateau prouvé deux fois, ~0,01 par doublement restant |
| encodeurs locaux de même famille | quatre candidats à 0,006 près |
| dimensions supplémentaires (512 → 3 072) | +0,040 seulement |
| plus proches voisins | perd sur les six axes |
| noyau RBF | « gagne » en écrasant la dispersion — faux gain |
| réseau de neurones derrière l'encodeur | −0,003 ; ne peut pas retrouver ce que l'encodeur a jeté |
| relever la troncature à 12 000 caractères | corrélation longueur×erreur ≈ 0 |
| critiques TMDB côté séries | 2,6 % de couverture sur la tête |
| distillation sur processeur, 256 tokens | 0,937 — la moitié du gain abandonnée |

## 5. Les trois commandes du quotidien

```bash
docker compose run --rm admin training note --limit 500 --apercu            # séries
docker compose run --rm admin training note --limit 500 --univers movies --apercu
docker compose run --rm admin training poids
```

Et pour vérifier une œuvre qui étonne : `training diagnostic --focus <id>`.
