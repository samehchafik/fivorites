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

## 2. Entraîner

L'attention coûte le **carré** de la longueur : c'est elle qui décide du temps,
pas le nombre de paramètres. D'où l'écart entre les deux chemins.

| | 20 000 paires, 3 époques |
|---|---|
| 1 GPU loué (T4, A10, 4090) | **< 1 h, 1 à 3 $** |
| Serveur, 1 024 tokens | plusieurs jours |
| Serveur, **256 tokens, 4 couches gelées** | ~10 à 20 h |

### Sur GPU

```bash
uv sync
uv run python distiller.py --corpus corpus.jsonl --sortie eleve-distille
```

### Sur le serveur, sans GPU

En conteneur, comme le reste : Debian 11 ne fournit que Python 3.9, et rien
n'est installé hors Docker sur cette machine. L'image embarque torch **en
version processeur** — la roue par défaut apporte deux gigaoctets de CUDA pour
du matériel qui n'existe pas ici — et le modèle de départ, téléchargé à la
construction pour qu'un entraînement de vingt heures ne meure pas à la première
minute sur un aléa réseau.

```bash
sudo docker compose --profile cli build distillation
```

Le corpus doit être dans `export/`, où `training corpus-export` l'a écrit :

```bash
sudo docker compose run --rm -d distillation \
    --corpus corpus.jsonl --sortie eleve-distille \
    --longueur 256 --geler 4 --lot 16 --fils 4
```

```bash
sudo docker logs --follow $(sudo docker ps -q --filter ancestor=fivorites-v2/distillation:latest)
```

Tout vit dans `export/` : le corpus lu, `reprise.pt` écrit, l'élève produit.
Rien dans le conteneur — c'est la condition pour qu'une coupure ne coûte que
les derniers lots.

Les trois réglages qui rendent ça tenable :

- **`--longueur 256`** — le facteur étant quadratique, passer de 1 024 à 256
  divise le temps par bien plus que quatre. Et la tête du dossier tient dans
  256 tokens : titre, faits, genres, mots-clés, début du synopsis. C'est elle
  qui porte le ton.
- **`--geler 4`** — la passe arrière pèse les deux tiers du calcul et ne remonte
  plus que jusqu'à la première couche entraînée. Les couches basses portent la
  syntaxe, les hautes le sens : c'est le sens qu'on déplace ici.
- **`--fils`** — le nombre de cœurs laissés au calcul. En laisser au moins un
  à l'admin, qui continue de servir le catalogue.

`--limite 8000` coupe le corpus si tu veux un premier résultat en une nuit
plutôt qu'un résultat complet en deux.

### Copier l'élève dans l'image admin

Une fois `export/eleve-distille/` produit, il faut qu'`admin` le voie. Le plus
simple, sans reconstruire d'image : le monter.

```yaml
    volumes:
      - ./www:/srv/www:ro
      - ./export/eleve-distille:/opt/models/eleve-distille:ro
```

Puis `EMBEDDER=local:/opt/models/eleve-distille` dans le `.env`.

### La reprise

Le script écrit `reprise.pt` tous les 200 lots et à chaque fin d'époque. Il
suffit de relancer **la même commande** : il repart à l'époque et au lot où il
s'était arrêté, avec l'optimiseur et le planning dans l'état exact. Une coupure
coûte au pire les derniers lots.

Le mélange des exemples est semé par l'époque, pas laissé au hasard — sans ça
une reprise rejouerait d'autres exemples, et l'époque serait à la fois
incomplète et partiellement doublée.

Pour repartir de zéro : supprimer `reprise.pt`.

### Le témoin

Le script affiche le cosinus **avant** tout entraînement. S'il ne monte pas,
quelque chose ne va pas — et le script refuse d'exporter plutôt que d'écrire un
élève inutile.

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
