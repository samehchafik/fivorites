# Étude — trois sources complémentaires : Wikidata, TVmaze, IMDb

> Mesure réalisée le 2026-08-06 · script : [`tools/etude_sources_complementaires.py`](../tools/etude_sources_complementaires.py)
> Données brutes : `etude_sources_complementaires.json`
>
> **Échantillon** : 230 séries de l'export TMDB du 2026-08-06 — 15 par décile de
> popularité (150), plus les 40 séries les plus populaires en écriture arabe et
> les 40 en écriture turque.
>
> L'étude ne touche ni la base ni l'API TMDB : elle part de l'export public.
> C'était nécessaire — le jeton TMDB est refusé et `raw_source` est vide, donc
> aucun `imdb_id` collecté n'était disponible comme point d'entrée.

## Ce qu'on demandait à chacune

| Source | Ce qu'on en attend | Licence | Suite |
|---|---|---|---|
| **Wikidata** | pays, langues, relations, identifiants manquants | CC0 | retenue |
| **TVmaze** | dates, épisodes, calendriers de diffusion | CC BY-SA 4.0 | retenue |
| **IMDb Datasets** | notes, titres alternatifs, identifiants | **non commercial** | **écartée** (volet 3) |

---

## Volet 1 — Le raccordement : qui trouve quoi

Sur les 230 séries, chaque source a été interrogée par le seul point d'entrée
disponible, l'identifiant TMDB.

| Indicateur | Part des 230 |
|---|---|
| Item Wikidata (`P4983`) | 38,7 % |
| …dont identifiant IMDb (`P345`) | 35,7 % |
| …dont identifiant TVmaze (`P8600`) | 27,8 % |
| **Série trouvée sur TVmaze** | **40,0 %** |
| Note IMDb disponible | 34,3 % |

### Le résultat le plus utile : TVmaze trouve plus que Wikidata

40,0 % contre 38,7 %, et surtout **par un autre chemin**. Le détail des voies :

| Voie | Séries trouvées |
|---|---|
| identifiant TVmaze porté par Wikidata (`P8600`) | 64 |
| lookup par `imdb_id` | 2 |
| **recherche par titre** | **26** |

Ces 26 séries appariées par titre comprennent **19 séries de la strate par
décile qui n'ont aucun item Wikidata** — 12,7 % de la strate. C'est le gain de
raccordement le plus net mesuré jusqu'ici, et il ne coûte ni clé ni quota.

### L'appariement par titre, mesuré contre une vérité terrain

Les 64 séries qui portent à la fois `P4983` et `P8600` dans Wikidata sont des
paires TMDB↔TVmaze déjà vérifiées par des humains. En rejouant la recherche par
titre sur ces 64 paires
([`tools/mesure_appariement_tvmaze.py`](../tools/mesure_appariement_tvmaze.py)) :

| Signal | Résultat |
|---|---|
| Top 1 correct, titre seul | **58 / 64** (90,6 %) |
| …que le seuil « score ≥ 0,9 » accepte | 35 / 58 — il en **rejette 23 de bons** |
| Faux positif passant le seuil | 1 (*Teen Wolf* → l'homonyme) |
| `externals.imdb` présent sur le top 1 | 51 |
| …confirme le bon appariement | 50 / 51 |
| …**oppose son veto au seul faux positif** | 1 / 1 |

Le seuil de score initial (≥ 0,9) est donc doublement mauvais : trop strict — il
jette 23 bons appariements sur 58 — et insuffisant, puisque le seul homonyme le
franchit (deux séries s'appellent *Teen Wolf* ; aucun score textuel ne les
départagera jamais).

Le bon protocole se lit dans le tableau : **titre pour chercher, `imdb_id` pour
décider**. La réponse de recherche TVmaze embarque `externals.imdb`
gratuitement ; l'égalité avec l'`imdb_id` de TMDB (`external_ids`, collecté dans
chaque fiche) confirme 50 cas sur 51 et rejette l'unique erreur. Quand
l'identifiant manque d'un des deux côtés (13 cas sur 64), on départage par les
signaux secondaires : année de première diffusion, pays, et recouvrement des
personnes — créateurs et distribution, que TVmaze expose et que TMDB fournit via
`aggregate_credits`. Ce dernier signal n'a pas pu être mesuré ici : il exige les
fiches TMDB, et `raw_source` est vide tant que le jeton n'est pas réparé.

### Par décile : tout s'effondre après le troisième

| Décile | Item Wikidata | Série TVmaze |
|---|---|---|
| 1 | 73,3 % | 80,0 % |
| 2 | 60,0 % | 60,0 % |
| 3 | 26,7 % | 26,7 % |
| 4 | 13,3 % | 20,0 % |
| 5 | 13,3 % | 20,0 % |
| 6 | 6,7 % | 26,7 % |
| 7 | 13,3 % | 20,0 % |
| 8 | 33,3 % | 26,7 % |
| 9 | 26,7 % | 20,0 % |
| **10** | **0,0 %** | **6,7 %** |

**Aucune des trois sources ne voit le fond de catalogue.** Au dernier décile,
Wikidata ne connaît rien et TVmaze une série sur quinze. C'est une donnée de
périmètre pour le lot 5 : au-delà du troisième décile, l'enrichissement externe
cesse d'être une stratégie.

### Par strate

| Strate | Séries | Wikidata | IMDb | TVmaze | Article ar | Résumés d'épisode |
|---|---|---|---|---|---|---|
| déciles | 150 | 26,7 % | 22,0 % | 30,7 % | 2,7 % | 17,3 % |
| **arabe** | 40 | 40,0 % | 40,0 % | 27,5 % | 35,0 % | **7,5 %** |
| **turc** | 40 | **82,5 %** | **82,5 %** | **87,5 %** | 65,0 % | 10,0 % |

Le corpus turc se raccorde presque partout, et TVmaze y fait mieux que Wikidata.
Le corpus arabe reste à 40 % — et `P4983` n'y apporte rien de plus que `P345`,
les deux colonnes étant identiques. Cela confirme la mesure du 2026-08-06 :
6 séries de langue arabe seulement portent un identifiant TMDB sans identifiant
IMDb dans tout Wikidata.

---

## Volet 2 — TVmaze : ce qu'elle donne vraiment

Sur les 92 séries trouvées :

| Indicateur | Part des trouvées |
|---|---|
| Statut (en cours / terminée) | 100 % |
| Diffuseur (network ou webChannel) | 100 % |
| Date de première diffusion | 98,9 % |
| Calendrier de diffusion (jours, heure) | 84,8 % |
| **Épisodes datés** | **99,2 %** (6 430 sur 6 482) |
| **Au moins un résumé d'épisode** | **35,9 %** |

### Verdict

**TVmaze est un raccordeur et une source de faits, pas une source de texte.**
Elle répond magnifiquement à « quand et où ça passe » — 99,2 % des 6 482
épisodes rencontrés portent une date de diffusion, ce que TMDB ne garantit nulle
part — et très mal à « de quoi ça parle ». Une série trouvée sur trois seulement
a des résumés d'épisode, et la médiane cumulée n'atteint 2 094 caractères que sur
la strate par décile ; elle tombe à 727 sur le corpus arabe.

Autrement dit : elle sert les **facettes d'usage** et la fiche produit, pas la
notation des 6 axes. Il ne faut pas attendre d'elle qu'elle comble le trou de
matière textuelle mesuré dans l'étude arabophone.

---

## Volet 3 — IMDb : écartée le 2026-08-06

> **Décision prise.** IMDb sort du plan — ni datasets, ni scraping. La mesure
> ci-dessous est conservée parce que c'est elle qui a permis de trancher.

`title.ratings.tsv.gz` fait 8 Mo compressés et se charge en entier. Sur les
230 séries, la note est disponible pour 34,3 % — mais surtout pour **96,3 % des
séries dont on a résolu l'identifiant IMDb**. C'était le rendement le plus élevé
des trois sources : une fois l'`imdb_id` connu, la note est là quasi
systématiquement, pour un fichier quotidien et aucune requête par série.

Trois raisons de s'en passer quand même.

**La licence interdit l'usage commercial** — « personal and non-commercial use »,
écrit sans ambiguïté. Et le scraping ne contourne rien : les conditions d'IMDb
l'interdisent explicitement, et le droit *sui generis* des bases de données
couvre **l'extraction**, pas seulement la republication. Ne pas publier les
données n'y change donc rien.

**L'apport marginal est plus mince qu'il n'y paraît.** Les titres alternatifs et
les identifiants externes sont déjà dans le `SERIES_APPEND` de la collecte TMDB
(`alternative_titles`, `external_ids`), tout comme les votes. Ce qu'IMDb ajoutait
réellement, c'était la robustesse de la note — et encore : médiane de 1 675
votes, mais 7 des 79 séries notées en ont moins de 50. Une note bâtie sur cinq
votes n'est pas une note.

**Et la note ne nourrit aucun des 6 axes.** Luminosité, Intensité, Humour,
Exigence, Étrangeté, Charge sensorielle décrivent un contenu, pas une qualité.
Le vecteur se construit sur du texte ; c'est là qu'est le manque, pas sur les
notes.

`title.akas` (plus de 300 Mo) n'a jamais été mesuré et ne le sera pas.

---

## Volet 4 — Wikidata : les faits, pas le raccordement

Sur les 89 items trouvés :

| Indicateur | Part des items |
|---|---|
| Pays d'origine (`P495`) | 97,8 % |
| Langue originale (`P364`) | 69,7 % |
| Nombre médian de sitelinks | 5 |

Quand l'item existe, **il porte le pays presque toujours**. C'est exactement ce
que demande la taxonomie « origine » identifiée comme première dimension du SEO
arabe. La langue est moins bien tenue — 69,7 % — ce qui explique au passage
pourquoi le comptage des séries de langue arabe dans Wikidata (663) est un
plancher et non une mesure.

La leçon de la mesure précédente tient : **Wikidata est excellente pour les faits
et médiocre comme porte d'entrée.** 38,7 % de raccordement, contre 40 % pour
TVmaze qui est pourtant une base bien plus petite.

---

## Synthèse : quoi faire, dans quel ordre

### 1. TVmaze d'abord

C'est la seule des trois qui améliore le **raccordement** (12,7 % de séries
récupérées par titre là où Wikidata ne connaît rien), et elle apporte des faits
que TMDB ne donne pas de façon fiable : dates d'épisode à 99,2 %, calendrier,
diffuseur. Gratuite, sans clé, CC BY-SA avec attribution — la licence la plus
simple des trois après CC0.

Dans `riche_source` : `source = 'tvmaze'`, `resolved_by` valant `p8600`, `imdb`
ou `title`, `content` recevant les résumés d'épisode **quand ils existent**, et
les faits partant vers la couche 1 au lot 4. Le protocole d'appariement est
celui mesuré au volet 1 : titre pour chercher, égalité `imdb_id` pour décider,
personnes et année en départage quand l'identifiant manque — pas de seuil de
score.

### 2. Wikidata pour les faits

Pays à 97,8 %, langues à 69,7 %, plus P915/P840 déjà au plan du lot 3. CC0, donc
aucune exposition. À ne pas utiliser comme entrée unique.

### 3. Rien après — et surtout pas IMDb

Écartée (volet 3). Ce qu'elle apportait de réutilisable est déjà collecté par
TMDB ; ce qu'elle apportait en plus ne nourrit aucun des 6 axes. **Le prochain
gain n'est pas dans une quatrième source, il est dans le jeton TMDB** : tant
qu'il est refusé, `raw_source` est vide, donc le signal « personnes » de
l'appariement, la matière textuelle des fiches et tout le lot 3 restent bloqués
derrière une variable d'environnement.

### Ce que l'étude ne résout pas

Le corpus arabe reste à 40 % de raccordement et 7,5 % de résumés d'épisode.
**Aucune des trois sources ne le débloque.** La conclusion de l'étude arabophone
tient donc telle quelle : source dédiée (elCinema, Shahid, recherche par titre
dans Wikipédia arabe) ou rien.

Et le fond de catalogue — déciles 8 à 10 — reste invisible aux trois. Si le
périmètre notable s'arrête au troisième décile, c'est une décision à prendre en
connaissance de cause, pas un accident.

---

## Limites

- **230 séries**, dont 40 par corpus. Les strates arabe et turque sont prises au
  sommet de la popularité : c'est le meilleur cas, pas la moyenne.
- **La détection du corpus se fait sur l'écriture du titre original.** L'arabe est
  fiable (alphabet distinct) ; le turc, détecté par `[ğışĞİŞ]`, rate les titres
  sans ces lettres — *Kara Sevda*, *Ezel*. La strate turque est un sous-ensemble
  biaisé vers les titres qui les contiennent.
- **L'appariement par titre a été validé contre 64 paires** (volet 1) — mais la
  vérité terrain vient de Wikidata, donc de séries plutôt bien documentées.
  Sa précision sur le fond de catalogue, où les homonymes sont moins départagés,
  reste à démontrer.
- **`title.akas` n'a pas été mesuré** — les titres alternatifs sont donc une
  promesse non vérifiée, volontairement, tant que la licence n'est pas levée.
- Un seul point de mesure dans le temps.
