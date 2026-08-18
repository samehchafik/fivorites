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

Six hypothèses sur le plafond de la régression, éliminées par la mesure :

| hypothèse | verdict |
|---|---|
| **Le volume** | deux plateaux mesurés (241→298, 346→521) |
| ~~**L'encodeur**~~ | **fausse élimination — voir ci-dessous** |
| **La calibration** | corrigée : 93–103 % d'amplitude restituée |
| **Le voisinage** | les plus proches voisins **perdent** sur les six axes (−0,085) |
| **La forme du modèle** | noyau RBF +0,037, réseau à trois couches −0,003 |
| **L'absence de Wikipédia** | 427 des 502 œuvres notées l'avaient déjà, avant d'être jugées |

L'échec des voisins est instructif en soi : si le voisinage dans l'espace des
embeddings correspondait au ton, la moyenne des notes voisines serait bonne.
Elle ne l'est pas, et leur dispersion s'effondre à 59–91 %.

Le gain du noyau est un faux gain, et c'est la colonne `dispersion` qui le dit :
70–85 % contre 90–100 % pour la ridge. Il achète son erreur moyenne en rangeant
tout vers le centre — exactement le tassement qu'on cherche à supprimer. La
ridge reste le bon modèle.

Le réseau, lui, était condamné par l'arithmétique avant d'être lancé : sur 512
entrées, la première couche pèse 96 % des poids, `512 × n₁` écrase le reste, et
aucune largeur de couche ne déplace ce rapport. Mesuré : −0,003.

**Trois familles très différentes — linéaire, à noyau, non linéaire profonde —
arrivent au même mur à 1,0 de MAE.** Ce n'est pas le modèle.

### L'encodeur : une élimination qui n'en était pas une

La ligne barrée du tableau est la plus instructive de ce document. « Trois
candidats à 0,006 près » ne disait pas ce qu'on lui a fait dire. Les quatre
candidats — jina small, jina base, nomic, bge — sont **de la même famille** :
tous petits, tous entraînés pour la similarité sémantique. Leur égalité établit
qu'ils sont interchangeables **entre eux**. Elle n'établit rien sur un encodeur
d'une autre nature.

Le voisinage de Lucifer a rendu la question concrète : ses dix plus proches
sont des policiers sombres, moyenne de joie 3,0 quand le juge la met à 6,0. Or
le titre de la série **est dans le dossier**. L'encodeur lisait le mot sans
savoir ce qu'il désigne.

Mesuré le 2026-08-12, sur les mêmes 502 œuvres et la même régression :

| encodeur | dims | MAE cv | joie |
|---|---|---|---|
| `jina-v2-small` | 512 | 1,020 | 1,14 |
| `text-embedding-3-large@512` | 512 | **0,853** | 0,94 |
| `text-embedding-3-large` | 3072 | **0,813** | 0,89 |

La variante `@512` est le contrôle qui rend la mesure concluante : **à
dimension égale**, le gain est de −0,167, et les 2 560 dimensions
supplémentaires n'ajoutent que 0,040. Ce n'est pas la taille du vecteur, c'est
la connaissance du modèle.

Les six axes progressent de 0,15 à 0,27. L'écart au bruit propre du juge (0,37)
passe de 0,65 à 0,44 : **un tiers du plafond, après quatre leviers stériles.**

La leçon de méthode : une hypothèse ne se déclare éliminée qu'au regard de ce
que le test faisait **varier**. Ici il faisait varier la marque de l'encodeur,
pas sa nature — et on a lu « l'encodeur n'y est pour rien » dans un résultat
qui disait « ces quatre-là se valent ».

**Le cas qui résiste à tout** : Lucifer. Le juge la note 6 en joie et 4 en peur
(confiances 0,79–0,94) ; la ridge rend 3,1 et 6,2. Ce n'est pas une erreur
d'échelle mais **de rang** — le modèle la classe 98ᵉ sur 502 en joie quand le
juge la met 290ᵉ. Vérifié : un transport de quantiles la laisserait à 3.

Le dossier ne raconte qu'un policier surnaturel ; la comédie est dans le jeu.
Même panne que la réflexion de House, et que l'axe `humour` de l'ancien barème
resté bloqué à 1,25 malgré volume, encodeur et visuels. **Trois confirmations
indépendantes que le ton n'est pas dans le texte encodé.**

*Résolution, 2026-08-13 :* avec `text-embedding-3-large@512` en production, la
joie de Lucifer n'est plus l'axe le plus faux. Ses dix voisins passent des
policiers sombres (Supernatural, Criminal Minds, SVU) à un mélange qui inclut
Only Murders in the Building et Wednesday — l'encodeur savait ce que « Lucifer »
désigne. L'erreur résiduelle est du même genre en plus petit : tristesse jugée
4,0, prédite 6,1, et la moyenne des voisins est 6,0. Le modèle rend toujours la
moyenne de son voisinage — le voisinage est simplement devenu meilleur. Et les
cosinus entre voisins tombent de 0,90 à 0,72 : le nuage s'est déplié, la
similarité entre œuvres redevient discriminante.

### La distillation : mesurée, et rangée

L'idée : apprendre à jina à reproduire les vecteurs du professeur, pour garder
le gain sans dépendre d'une API. Le corpus n'a besoin d'aucune note du juge —
25 001 paires `dossier → vecteur` constituées pour ~4 $, la seule donnée du
projet qui ne soit pas bornée par les œuvres notées.

Entraîné sur le serveur, sans GPU : 22 485 paires, 256 tokens, une couche
gelée, ~20 h. Cosinus de distillation 0,7505. Mesuré le 2026-08-14 sur 937
œuvres notées :

| encodeur | MAE cv | joie | tristesse |
|---|---|---|---|
| professeur `text-embedding-3-large@512` | **0,834** | 0,90 | 0,85 |
| élève distillé | 0,937 | 1,03 | 1,04 |
| jina d'origine | 1,017 | 1,11 | 1,06 |

L'élève récupère **44 % de l'écart** — pronostic annoncé avant la mesure :
0,90–0,95. Il bat jina sur les six axes et égale le professeur sur `rêve`,
mais `joie` et `tristesse`, les axes du ton, restent au niveau de jina :
**il a appris la géométrie générale, pas les nuances qui manquaient.**

Verdict : l'API reste en production. Le catalogue entier coûte ~43 $ une
fois, ~0,0002 $ par œuvre nouvelle ensuite ; déployer l'élève économiserait
ça au prix de la moitié du gain. L'élève et son corpus restent sur disque
(`export/`, projet `distillation/`) — une heure de GPU louée avec 1 024
tokens ferait sans doute mieux, le jour où la dépendance API deviendra un
vrai problème.

Au passage, le professeur confirme que **le volume paie enfin** : 0,853 sur
502 œuvres, 0,834 sur 937. Le levier qui plafonnait dans l'espace de jina
fonctionne dans le nouvel espace.

---

## 7 bis. La validité : « action 5,5 », est-ce vrai ?

Mesuré le 2026-08-15 sur 3 979 œuvres, par `training validite`. C'est la
première fois que le projet mesure autre chose que sa propre cohérence.

**La distinction qui manquait.** Tout ce qui précède mesure la **fidélité** :
le juge d'accord avec lui-même (0,37), la régression d'accord avec le juge
(0,84). Ça établit qu'on rend toujours la même valeur, pas qu'elle soit la
bonne — un thermomètre déréglé de trois degrés est parfaitement fidèle.

| axe | ancres (écart) | genre (écart) | plancher réel |
|---|---|---|---|
| rêve | **0,50** | **+4,41** | **1,61** |
| action | 0,50 | +3,31 | 3,78 |
| joie | 1,00 | +2,85 | 3,88 |
| tristesse | 1,00 | +2,09 | 3,41 |
| peur | 1,50 | +2,78 | 3,28 |
| réflexion | **1,67** | **+1,86** | **4,78** |

### Ce qui est validé

**Le critère extérieur passe sur les six axes.** Les genres TMDB sont produits
par des éditeurs qui n'ont jamais vu ce barème, et pourtant les œuvres du genre
attendu scorent de +1,86 à +4,41 plus haut que les autres. Les axes mesurent
quelque chose que quelqu'un d'autre reconnaît.

**Et ce n'est pas une copie du genre.** Les moyennes « avec » valent 5,5 à 7,1,
pas 9 : une œuvre d'action moyenne fait 7,08 en action, et il reste de la
dispersion *à l'intérieur* du genre — ce qui est tout l'objet de l'exercice.
Le barème l'exige explicitement (« Score the emotion, never its genre label »)
et il est suivi.

### Ce qui est réfuté : le bas de l'échelle

Le juge s'écarte de **ses propres ancres** de 1,0 en moyenne, soit près de
trois fois son bruit propre. Et la direction est nette :

| ancre | déclaré | rendu |
|---|---|---|
| NCIS (réflexion) | 1 | **4,0** |
| Downton Abbey (peur) | 1 | **3,0** |
| Chernobyl (joie) | 1 | **2,0** |
| Breaking Bad (tristesse) | 6 | **8,0** |
| The Crown (rêve) | 2 | 1,0 |

Un seul contre-exemple. **Le bas de l'échelle est comprimé** : ce que le barème
définit comme 1 ressort entre 2 et 4. La colonne « plancher réel » — la moyenne
des œuvres hors du genre attendu — le confirme indépendamment : la plupart des
axes ne descendent jamais sous 3,3 à 4,8.

Cause probable : le prompt lui-même. Il insiste lourdement contre les notes
basses (« Scoring a work 1 or 2 on every dimension… is a serious error »), pour
corriger un défaut réel de la v1, et il a sur-corrigé.

**Conséquence pratique.** Le RANG est fiable — l'ordre entre deux œuvres tient,
et c'est ce dont la recommandation a besoin. La VALEUR absolue est gonflée
d'environ un point et demi dans la moitié basse : « action 5,5 » se lit « plutôt
4 dans les termes du barème ». Le zéro n'est pas au bon endroit, la règle est
bonne.

### Le meilleur et le pire axe

`rêve` est premier sur les trois mesures — meilleure fidélité aux ancres,
meilleure séparation par genre, seul axe qui utilise vraiment son bas (1,61).
C'est aussi le plus objectif à définir : « la distance au réel ».

`réflexion` est dernier sur les trois, avec un plancher à 4,78 : **il ne dit
presque jamais qu'une œuvre ne fait pas réfléchir.** Son test de genre ne repose
en outre que sur 81 documentaires. À ne pas afficher tel quel.

### Le point aveugle

**Zéro contre-note en base.** Le code appelle Haiku quand sa clé est présente,
mais aucune campagne ne l'a jamais rempli. Sans second juge d'une autre lignée,
rien ne distingue une mesure d'une convention propre à GPT. C'est le trou le
moins cher à combler du projet.

### Ce que ça ouvre

Pour la première fois, **un barème se juge sur autre chose que sa cohérence
interne**. Les itérations v1→v2→v3 se réglaient sur des corrélations entre
axes ; il existe maintenant un critère externe et un test de reproduction des
définitions. Un `empreinte-v4` qui exigerait d'utiliser le bas de l'échelle
serait *vérifiable* : les ancres à 1 doivent ressortir à 1. Coût du cycle
complet ~4 $ pour renoter 3 979 œuvres — et le gain se mesure au lieu de
s'espérer.

Note sur les genres non revendiqués (crime 561, familial 529, romance 318…) :
c'est délibéré. Aucun ne correspond à une émotion du barème — le crime n'est pas
la peur, la romance n'est pas la tristesse — et les rattacher affaiblirait le
critère au lieu de l'élargir.

---

## 8. Ce qui reste ouvert

**1. L'asymétrie entre ce que lit le juge et ce que lit l'encodeur.** C'est
l'hypothèse vivante, et elle n'a jamais été mesurée. GPT reçoit le dossier
entier ; `embed_texts` le tronque à `MAX_CHARS` = 12 000 caractères. Pour toute
fiche qui dépasse, la note à prédire dépend d'un texte que le vecteur n'a jamais
vu. Le réordonnancement des sections a déplacé la coupe vers les synopsis
répétitifs, il ne l'a pas supprimée.

```bash
sudo docker compose run --rm admin training diagnostic --focus 63174
```

Gratuit. La corrélation longueur × erreur tranche : plate, la troncature est
hors de cause ; croissante, relever la borne devient le levier.

**2. Le voisinage de Lucifer**, rendu par la même commande via `--focus`. Si ses
dix plus proches sont *Supernatural*, *Constantine*, *Grimm*, tous notés bas en
joie par le juge, alors aucun modèle ne peut deviner qu'elle est drôle : le
plafond est dans l'encodeur. C'est la question qui passe avant le choix d'un
modèle — aucune régression ne retrouve ce que la représentation ne contient pas.

**3. Le rapport exemples/dimensions.** 502 exemples pour 512 dimensions, soit
1:1 — le pire régime pour un modèle non linéaire. Deux façons d'en sortir :
noter ~5 000 œuvres (≈ 20 $, 3 à 5 heures), ou **réduire les dimensions** par
ACP, ce qui donne le même rapport gratuitement et profite à tous les modèles.

C'est aussi la seule voie qui rendrait un réseau pertinent. À 512 entrées, la
première couche pèse 16 384 poids pour ~345 exemples ; réduire à 32 composantes
et partager un tronc entre les six sorties donne 718 poids pour 2 070 cibles,
soit trois cibles par poids au lieu d'un cinquantième. Tant que ce rapport n'est
pas corrigé, discuter du nombre de neurones par couche n'a pas de sens.

**4. Le §5 de [`v2-notation-axes.md`](v2-notation-axes.md)** décrit toujours le
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
| `training diagnostic --focus ID` | ce que la troncature emporte, et le voisinage d'une œuvre (gratuit) |
| `training encodeurs` | comparer les encodeurs (gratuit) |
| `training visuels` | ce que les légendes apportent et coûtent (gratuit) |
| `sourcing enrich --order popularity` | Wikipédia, Wikidata, TVmaze (gratuit) |
| `sourcing videos` | projeter les bandes-annonces du brut (gratuit) |
| `sourcing videos-check --age 30` | vérifier que les vidéos vivent (gratuit) |

Rappel qui a coûté deux lots : **les migrations sont copiées dans l'image, pas
montées.** Après un `git pull`, il faut `docker compose build` avant que
`db migrate` voie quoi que ce soit — et `docker compose run` ne reconstruit
jamais.
