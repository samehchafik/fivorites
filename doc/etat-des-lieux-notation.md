# La notation : état des lieux au 2026-08-11

Journal des deux journées qui ont fait basculer le référentiel et poussé la
régression interne dans ses retranchements. Écrit pour qu'on n'ait pas à
refaire les mêmes mesures dans trois mois.

Ordre de lecture si tu es pressé : le §7 dit ce qui est **établi**, le §8 ce
qui **reste ouvert**. Le reste explique comment on y est arrivé.

Tout ce qui suit porte sur les **séries**. Le pendant film — ce qui se duplique,
ce qui résiste, et dans quel ordre — est dans
[`mission-notation-films.md`](mission-notation-films.md).

---

## 1. Le changement principal : un autre référentiel

Les six **axes de goût** — `luminosite`, `intensite`, `humour`, `exigence`,
`etrangete`, `sensoriel` — ont été remplacés par les six dimensions de
l'**empreinte culturelle** du programme de R&D (§4.5.1.5) : `joie`, `reve`,
`tristesse`, `peur`, `reflexion`, `action`.

**Ce n'est pas un renommage.** Les premiers sont des positions bipolaires
(`luminosite 2` = sombre, `9` = lumineux) ; les seconds sont des composantes
d'un mélange (`peur 2` = peu de peur, pas « le contraire de la peur »). La
distance change de nature avec eux — cosine plutôt qu'euclidienne pondérée — et
tout le §5 de [`v2-notation-axes.md`](v2-notation-axes.md), qui décrit le
vecteur utilisateur en « position + tolérance », est à réécrire.

L'analyse d'impact complète est dans
[`mission-empreinte-culturelle.md`](mission-empreinte-culturelle.md). Le point
qui a rendu la bascule peu coûteuse : la liste des axes est une **donnée**, pas
du code. `notation.score` a une ligne par axe, tout le back lit
`rubric["axes"]`, et le schéma JSON de sortie du juge se construit depuis cette
liste. La bascule a donc tenu en une migration et six libellés dans le front.

---

## 2. Trois versions de barème, et ce que chacune a appris

### `empreinte-v1` — la première rédaction

Mesurée sur 52 œuvres : les six dimensions **n'en font que deux**. ACP à
**63,9 %** sur la première composante, 80,9 % sur les deux premières.
`tristesse × peur` à **0,84**, `peur × action` à 0,80, et `joie` en négatif de
tout le bloc. Le juge ne mesurait pas six émotions mais une seule chose — la
gravité de la série. Effet de halo.

Second défaut : **zéro `null` sur 312 notes**, alors que sept œuvres
ressortaient notées 1 à 3 partout. Ce n'étaient pas des séries sans émotion,
c'étaient des dossiers maigres.

### `empreinte-v2` — corriger par la prose

Ajout d'un paragraphe d'indépendance en majuscules, d'une opposition explicite
entre `1` (l'émotion est absente) et `null` (le dossier ne permet pas de
trancher), et d'une ligne de démarcation par dimension.

**Résultat : rien.** Première composante 63,5 → 62,7 %. `tristesse × peur` :
0,84 → 0,84. Zéro `null`, toujours.

Le modèle avait pourtant bien lu — 48 œuvres sur 51 renotées différemment. La
leçon : **on ne supprime pas un effet de halo en demandant à un modèle de ne
pas en avoir.**

### `empreinte-v3` — corriger par les exemples

Le vrai levier était dans les **ancres**. `peur` était ancrée à 8 sur *The
Walking Dead* et à 10 sur *The Haunting of Hill House* — deux séries
terrifiantes **et** profondément tristes, la seconde étant littéralement un
récit de deuil. Juste au-dessus, la définition affirmait « This is NOT sorrow ».
Entre une assertion et un exemple, le modèle suit l'exemple.

La règle « aucune œuvre ne sert d'ancre à deux dimensions » était respectée à la
lettre — aucun titre partagé — mais pas dans l'esprit : ce n'est pas le partage
d'un titre qui enseigne la corrélation, c'est **l'uniformité de ton du haut de
l'échelle**. Le motif se vérifiait sur les six :

| dimension | information propre | ancres hautes |
|---|---|---|
| `reflexion` | 57 % | variées |
| `reve` | 53 % | **très** variées |
| `action` | 34 % | tendues, sombres |
| `joie` | 29 % | — |
| `tristesse` | 25 % | toutes graves |
| `peur` | 16 % | toutes graves |

Quatre remplacements, aucune définition retouchée : *American Horror Story* et
*Ash vs Evil Dead* pour `peur`, *BoJack Horseman* pour `tristesse`, *The
Mandalorian* pour `action`, *The Good Place* pour `reflexion`.

**Résultat, en bootstrap apparié sur les 52 mêmes œuvres :**

- `tristesse × peur` : 0,84 → **0,77**, IC95 [−0,145 ; −0,014], **p = 0,008**
- information propre de `peur` : **+5,8 pts**, p = 0,024
- `reflexion` +6,9 pts et `tristesse` +5,5 pts (tendance)
- **les deux témoins** (`joie` et `reve`, ancres inchangées) **n'ont pas bougé**

Changer quatre exemples change la mesure. Mais l'ampleur reste faible : il
aurait fallu 0,35 de baisse, on en a acheté 0,07.

---

## 3. Le verdict qui remet tout en perspective

Sur 52 œuvres, l'empreinte paraissait plus effondrée que les anciens axes. **À
volume égal, elles sont indistinguables.**

| | empreinte-v3 (502) | axes de goût (516) |
|---|---|---|
| Composante 1 | 51,7 % | 50,5 % |
| Cumul 1+2 | **70,7 %** | 75,3 % |
| Dimensions effectives | **3,00** | 2,98 |
| \|r\| moyen | 0,40 | 0,41 |
| Paire la plus liée | tristesse × peur 0,73 | luminosité × intensité 0,71 |

Décomposition de l'écart apparent, par bootstrap :

```
50,9 %   niveau de base (axes de goût, 52 œuvres tirées au hasard)
+6,6     effet du corpus  (ces 52 séries populaires précisément)
+5,2     effet du référentiel
──────
62,7 %   empreinte-v2 mesuré sur 52
```

**La moitié du surcroît venait du corpus, pas du barème.** Et les anciens axes
n'avaient jamais passé ce test non plus — on jugeait l'empreinte sur un critère
que rien n'avait rempli.

---

## 4. La régression interne

### La calibration visait la mauvaise cible

La ridge comprime ses prédictions vers la moyenne. Une calibration existait,
mais elle corrigeait la **pente de régression** `cov(y,p)/var(p)` — celle qui
minimise l'erreur quadratique, et qui laisse par construction
`sd(prédit) = r · sd(juge)`.

Avec un r de 0,84 à 0,93, il manquait encore 7 à 16 % d'amplitude **après**
correction. Mesuré : l'écart-type prédit valait **75 à 87 %** de celui du juge,
et Game of Thrones ressortait à 6,x sur quatre dimensions que le juge mettait
à 8.

Viser **l'écart-type** comble exactement cet écart, et — contre toute attente —
ne coûte rien :

| | avant | après |
|---|---|---|
| Amplitude restituée | 75–87 % | **93–103 %** |
| Amplitude par œuvre | 4,5 | **5,2** (juge : 5,4) |
| Similarité cosine moyenne | 0,902 | **0,859** (juge : 0,853) |
| MAE | — | inchangé, et meilleur sur `reve` (0,85 → 0,74) |

Le dernier chiffre est celui qui compte : la distance en aval est un cosine, et
des vecteurs tassés pointent tous au même endroit — **sans qu'aucun MAE ne le
signale**.

### Le vrai MAE est ~1,0, pas ~0,75

Les valeurs lues dans les exports (`interne`) sont celles du modèle final
appliqué à ses propres données d'entraînement. Le hors-pli honnête, rendu par
`training modeles`, donne **0,90 à 1,14 selon l'axe**. Le modèle est moins bon
que les exports le laissaient croire.

Pour mémoire, le bruit propre du juge — même dossier noté deux fois — avait été
mesuré à **0,37** sur l'ancien barème. C'est le plancher théorique.

---

## 5. Le dossier

### Wikipédia n'entrait jamais dans le vecteur

Le juge lit le dossier entier ; l'encodeur le tronque à `MAX_CHARS`
(12 000 caractères, borne imposée par la mémoire de l'attention) **en coupant la
fin**. Or Wikipédia était la dernière section.

Docteur House l'a révélé : la série est enrichie, GPT a lu l'article et lui a
donné 8 en réflexion, et le modèle interne prédisait 6,1. Huit saisons de
résumés saturaient le budget bien avant d'y arriver. Ce n'est pas un cas
limite — c'est le régime normal de toute série qui dure.

Le commentaire de `embed.py` affirmait le contraire (« coupe la fin de la
dernière section, pas une section entière ») : il ignorait laquelle était
dernière.

**Correctif** : ce qui *parle de l'œuvre* — Wikipédia, légendes — passe avant ce
qui *raconte l'intrigue*. House : 6,1 → 6,7.

### Les critiques : une fausse piste, documentée

`reviews` est dans `SERIES_APPEND` depuis le premier jour et le dossier ne le
lisait pas. J'ai ajouté la section en pensant tenir le signal de ton qui
manque — **et 0 dossier sur 502 a changé.**

Vérification faite après coup, qui aurait dû être faite avant :

| | catalogue entier | top 500 |
|---|---|---|
| Fiches avec critiques | 114 / 228 429 | **13 / 500** |

TMDB n'a presque pas de critiques pour la télévision, et `reviews` suit le
`language` de la requête sans paramètre pour l'élargir. La section est restée —
écrite, testée, gratuite à l'exécution, utile à ces treize-là — mais ce n'est
pas le levier cherché. **Lucifer n'a pas de critique.**

---

## 6. Le canal vidéo

Chantier distinct, mené en parallèle et terminé.

- **`sourcing.video`** : projection des vidéos du brut TMDB, dédoublonnées sur
  (hébergeur, clé), avec une colonne `priorite` qui range bande-annonce
  officielle avant teaser avant extrait.
- **`sourcing.video_scan`** : les séries examinées, **y compris celles sans
  aucune vidéo** — sans quoi chaque passe rouvrirait les mêmes fiches vides.
- **`fiv-sourcing videos`** : la projection. Aucun appel réseau, aucun quota.
- **`fiv-sourcing videos-check`** : vérifie que les vidéos sont encore lisibles,
  via les points oEmbed publics de YouTube et Vimeo. Les mortes sont
  **marquées, jamais supprimées**. Un hébergeur injoignable (429, 500, coupure)
  ne condamne rien — sans quoi une panne de YouTube viderait le catalogue.
- **Onglet Vidéos** dans la fiche : lecteur monté au clic seulement, vignettes
  statiques, intégration `youtube-nocookie`.

**Et une correction à la collecte** : `videos` suit le paramètre `language`
comme les images. La collecte demandant la fiche en `fr-FR`, on ne récupérait
que les bandes-annonces françaises. `include_video_language: "fr,en,null"` est
l'exact symétrique du `include_image_language` déjà présent.

Mesuré sur les 20 séries les plus populaires, avant/après re-collecte :
**10 → 17 séries avec vidéos**, 98 vidéos au total.

---

## 7. Ce qui est établi

Quatre hypothèses sur le plafond de la régression, éliminées par la mesure :

| hypothèse | verdict |
|---|---|
| **Le volume** | deux plateaux mesurés (241→298, 346→521) |
| **L'encodeur** | trois candidats à 0,006 près — jina, nomic, bge |
| **La calibration** | corrigée : 93–103 % d'amplitude restituée |
| **La forme du modèle** | les plus proches voisins **perdent** sur les six axes (−0,085) |

L'échec des voisins est instructif en soi : si le voisinage dans l'espace des
embeddings correspondait au ton, la moyenne des notes voisines serait bonne.
Elle ne l'est pas, et leur dispersion s'effondre à 59–91 %.

**Le cas qui résiste à tout** : Lucifer. Le juge la note 6 en joie et 4 en peur
(confiances 0,79–0,94) ; la ridge rend 3,1 et 6,2. Ce n'est pas une erreur
d'échelle mais **de rang** — le modèle la classe 98ᵉ sur 502 en joie quand le
juge la met 290ᵉ. Vérifié : un transport de quantiles la laisserait à 3.

Le dossier ne raconte qu'un policier surnaturel ; la comédie est dans le jeu.
Même panne que la réflexion de House, et que l'axe `humour` de l'ancien barème
resté bloqué à 1,25 malgré volume, encodeur et visuels. **Trois confirmations
indépendantes que le ton n'est pas dans le texte encodé.**

---

## 8. Ce qui reste ouvert

**1. La comparaison des modèles n'a pas été lancée en entier.** `training
modeles` compare désormais quatre candidats — ridge, voisins, noyau RBF, réseau
à trois couches. Seuls les deux premiers ont un résultat. C'est gratuit :

```bash
sudo docker compose run --rm admin training modeles
```

Un contrôle XOR verrouille le banc : la ridge doit y échouer, les trois autres
doivent le lire. Il a servi trois fois — il a montré que le réseau plafonnait
avec une descente à inertie (corrigée par Adam), puis qu'il apprenait son pli
par cœur parce qu'on réduisait les entrées, ce qui amplifiait trente dimensions
de bruit au niveau du signal.

**2. L'enrichissement Wikipédia n'a jamais été lancé sur le bon corpus.** C'est
le levier restant le plus prometteur, et il est **gratuit**. `enrich` avance par
identifiant, `training note` sélectionne par popularité : seules **43 des 521
œuvres notées** ont un enrichissement.

```bash
sudo docker compose run --rm sourcing enrich --order popularity --limit 700
sudo docker compose run --rm admin training poids
```

Détail dans
[`mission-enrichissement-dossier.md`](mission-enrichissement-dossier.md).

**3. Le diagnostic qui trancherait au bon niveau** — jamais construit. Regarder
les **voisins de Lucifer** dans l'espace des embeddings. Si ses dix plus proches
sont *Supernatural*, *Constantine*, *Grimm*, alors aucun modèle ne peut deviner
qu'elle est drôle : le plafond est dans l'encodeur, et ni le volume ni la forme
du modèle n'y changeront rien. Une vingtaine de lignes, aucun appel payant.

**4. Le rapport exemples/dimensions.** 502 exemples pour 512 dimensions, soit
1:1 — le pire régime pour un modèle non linéaire. Deux façons d'en sortir :
noter ~5 000 œuvres (≈ 20 $, 3 à 5 heures), ou **réduire les dimensions** par
ACP, ce qui donne le même rapport gratuitement et profite à tous les modèles.

**5. Le §5 de [`v2-notation-axes.md`](v2-notation-axes.md)** décrit toujours le
vecteur utilisateur en « position + tolérance ». Sur des composantes, ce
raisonnement s'inverse et la formule de score devient une similarité cosine. À
réécrire avant d'implémenter la distance.

---

## 9. Les erreurs de méthode, pour ne pas les refaire

**Livrer avant de vérifier que la donnée existe.** La section `VIEWER REVIEWS` a
été écrite, testée et déployée avant que quiconque ait compté les critiques en
base. Zéro dossier modifié. La vérification prenait une requête.

**Se disperser.** Trois tours ont été consacrés aux vidéos et aux critiques
pendant que la question posée était celle des poids. Les deux chantiers étaient
légitimes, l'ordre ne l'était pas.

**Poser trop tard la bonne question.** « Est-ce la forme du modèle ? » n'a été
posée qu'après le volume, l'encodeur, la calibration, le prompt et le dossier.
Elle coûtait une commande.

**Confondre erreur d'ajustement et erreur de généralisation.** Les `maeFit` des
exports flattent : ils mesurent le modèle sur ses propres données. Seul le
hors-pli dit quelque chose.

---

## 10. Les commandes utiles

| | |
|---|---|
| `training note -n N` | noter N œuvres avec le juge (payant, ~0,004 $/œuvre) |
| `training poids` | entraîner la régression et régénérer les vecteurs (gratuit) |
| `training modeles` | comparer ridge / voisins / noyau / réseau (gratuit) |
| `training encodeurs` | comparer les encodeurs (gratuit) |
| `training visuels` | ce que les légendes apportent et coûtent (gratuit) |
| `sourcing enrich --order popularity` | Wikipédia, Wikidata, TVmaze (gratuit) |
| `sourcing videos` | projeter les bandes-annonces du brut (gratuit) |
| `sourcing videos-check --age 30` | vérifier que les vidéos vivent (gratuit) |

Rappel qui a coûté deux lots : **les migrations sont copiées dans l'image, pas
montées.** Après un `git pull`, il faut `docker compose build` avant que
`db migrate` voie quoi que ce soit — et `docker compose run` ne reconstruit
jamais.
