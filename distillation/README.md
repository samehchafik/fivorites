# Distiller le professeur dans l'élève

Apprendre à `jina-v2-small` — 33 M de paramètres, local, gratuit — à reproduire
la représentation de `text-embedding-3-large@512`, qui est une API payante.

## Pourquoi

Mesuré sur les 502 œuvres notées, à dimension égale :

| encodeur | MAE cv |
|---|---|
| `jina-v2-small` | 1,020 |
| `text-embedding-3-large@512` | **0,853** |

L'écart ne vient pas du nombre de dimensions — la variante 3 072 n'ajoute que
0,040 de plus. Il vient de ce que le gros modèle **sait** : jina lit le mot
« Lucifer » sans savoir ce qu'il désigne, et range la série chez les policiers
sombres, où 2,6 en joie est la bonne réponse pour ce voisinage. Le juge la met
à 6,0.

La distillation vise à récupérer l'essentiel de cet écart sans payer d'API à
chaque œuvre. Attente raisonnable : **~0,88**, soit 80 à 95 % du gain, gratuit
à l'usage et sans dépendance réseau.

## Ce que ce script ne fait pas

Apprendre une petite projection par-dessus un jina **gelé**. Ce serait trente
secondes de calcul sans GPU — et ça ne servirait à rien. Une fonction du
vecteur de jina ne peut pas retrouver ce que jina a jeté ; c'est le même
argument qui a condamné le réseau à trois couches posé derrière la régression.
Il faut réentraîner le corps de l'encodeur, sinon on n'a rien distillé.

## 1. Sortir le corpus

Depuis le serveur, dans le dépôt :

```bash
sudo docker compose run --rm -v "$PWD:/sortie" admin \
    training corpus-export --sortie /sortie/corpus.jsonl
```

Une ligne par œuvre : `{idTmdb, univers, text, vector}`. Le texte est
réassemblé par le code qui sait le faire — il n'est pas stocké en base, seul
son sha l'est — et chaque paire est vérifiée contre ce sha : une œuvre enrichie
depuis son encodage est écartée plutôt que d'enseigner une correspondance
périmée.

Le corpus se remplit avec `training corpus`. **5 000 paires donnent un premier
signal, 20 000 un résultat exploitable** — la cible étant un vecteur de 512
nombres et non six notes, chaque œuvre apporte 512 signaux, ce qui rend ces
ordres de grandeur suffisants.

## 2. Louer une heure de GPU

| | 20 000 dossiers, 3 époques |
|---|---|
| CPU, 512 tokens | 5 à 16 h |
| CPU, 2 048 tokens | plusieurs jours |
| 1 GPU (T4, A10, 4090) | **< 1 h, 1 à 3 $** |

L'attention coûte le carré de la longueur : c'est elle qui décide, pas le
nombre de paramètres. Louer coûte moins cher que le corpus lui-même, et
n'installe rien sur le serveur.

```bash
uv sync
uv run python distiller.py --corpus corpus.jsonl --sortie eleve-distille
```

Réglages utiles : `--longueur` (1 024 par défaut — le dossier place en tête ce
qui porte le ton, la coupe tombe sur les synopsis d'épisodes répétitifs),
`--lot`, `--epoques`.

Le script affiche le cosinus **avant** tout entraînement. C'est le témoin :
s'il ne monte pas, quelque chose ne va pas, et le script refuse d'exporter.

## 3. Vérifier avant de déployer

Copier `eleve-distille/` dans l'image admin sous `/opt/models/`, puis :

```bash
sudo docker compose run --rm admin training encodeurs \
    --modeles local:/opt/models/eleve-distille,openai/text-embedding-3-large@512
```

C'est le seul juge qui compte : le MAE de validation croisée sur les œuvres
notées, pas le cosinus de distillation. Un élève peut très bien imiter le
professeur en moyenne et rater précisément ce qui sert à noter.

**Déployer seulement si l'écart au professeur est acceptable.** Ensuite :

```bash
EMBEDDER=local:/opt/models/eleve-distille
```

puis `training poids` pour réentraîner la régression dans le nouvel espace —
les poids portent l'étiquette de leur encodeur, et ceux de l'ancien ne seront
simplement plus relus.

## Ce qui reste vrai quoi qu'il arrive

L'élève ne dépassera jamais son professeur. Si un jour un meilleur encodeur
apparaît, c'est le corpus qu'on refait — il coûte quelques dizaines de dollars
— et la distillation se relance dessus. Rien de ce qui est en base n'est perdu :
`notation.embedding` range chaque vecteur sous l'étiquette de son modèle.
