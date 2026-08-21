# Étude — l'univers livre : couverture et sources

> Mesure réalisée le 2026-08-21 · script : [`tools/etude_couverture_livres.py`](../tools/etude_couverture_livres.py)
> Données brutes : `etude_couverture_livres.json`
>
> **Échantillon** : 30 œuvres par langue originale (fr, en, es, ar), les plus
> « connues » de Wikidata — tri par nombre de sitelinks, seul proxy de
> popularité gratuit en l'absence d'un export à la TMDB. C'est donc le
> **meilleur cas** de chaque corpus, comme dans l'étude arabe des séries.
>
> Trois limites du protocole, connues et assumées : le tri par P407 ramène
> quelques faux originaux (2 sur 120 repérés — Wikidata attribue parfois la
> langue d'une traduction à l'œuvre) ; l'inventaire des éditions Open Library
> est plafonné à 500 (atteint par *Le Petit Prince*, *1984*…) ; Google Books
> est écarté — son quota anonyme partagé répond 429 en permanence, une clé
> serait nécessaire.

## Le paysage : il n'y a pas de TMDB du livre

Pas de source unique qui donne à la fois l'identité, les traductions, la
matière textuelle et la disponibilité. Le rôle se répartit :

| Source | Ce qu'on en attend | Accès | Licence | Suite |
|---|---|---|---|---|
| **Open Library** | le pivot work/édition, les ISBN, les dumps mensuels | API libre, sans clé | données publiques | **retenue — première référence** |
| **Wikidata** | l'identité (P648, P50…), les traductions qualifiées (P629, P655) | SPARQL | CC0 | retenue (déjà dans le pipeline) |
| **Wikipédia** | la matière à notation | REST/API | CC BY-SA | retenue (déjà dans le pipeline) |
| **UNESCO Index Translationum** | l'historique des traductions 1979–2008, 829 377 notices | **API ouverte** (DataHub) | ouverte | retenue — amorce traductions |
| **BnF catalogue général** | le référentiel français, traducteurs compris | **SRU, sans clé** | ouverte | retenue — volet fr |
| Google Books | fraîcheur commerciale, liens d'achat | clé requise (429 sans) | ToS | en réserve |
| Hardcover | notes et tags communautaires (l'ex-API Goodreads) | GraphQL, gratuit | ToS | en réserve — signaux, pas référentiel |
| ISBNdb | ~30 M d'ISBN, prix marchands | payant | commerciale | écartée à ce stade |
| **Arabic Union Catalog** | ~2,5 M de notices arabes, autorités | **fermé (403 mesuré)** — adhésion | membre | **à négocier** (§6) |
| Dilicom / FEL, Electre | disponibilité commerciale fr | interprofessionnel | commerciale | à négocier si besoin (§6) |
| DILVE / CEGAL (todostuslibros) | disponibilité commerciale es | professionnel / API partenaire | commerciale | à négocier si besoin (§6) |
| WorldCat | filet multilingue | réservé bibliothèques membres | membre | écartée |

---

## Volet 1 — Raccordement : l'œuvre Wikidata se relie-t-elle à Open Library ?

Le protocole série transposé : l'identifiant pour décider (P648, l'OLID porté
par Wikidata), le titre pour chercher (recherche OL titre+auteur, puis titre).

| Indicateur | fr | en | es | ar |
|---|---|---|---|---|
| OLID direct (P648) | 93 % | 100 % | 77 % | **23 %** |
| résolu par recherche | 7 % | 0 % | 20 % | 60 % |
| **non raccordable** | 0 % | 0 % | 3 % | **17 %** |

Même géographie que pour les séries : l'Occident est cousu, l'arabe se
raccroche mal. Mais la recherche par titre arabe **fonctionne** dans OL
(60 % de rattrapage) — et les 17 % restants ont tous un QID, donc une
identité : le pivot `oeuvre` les accueille en attendant une réconciliation.

## Volet 2 — Traductions : qui les trouve

| Indicateur | fr | en | es | ar |
|---|---|---|---|---|
| éditions OL, médiane | 235 | 440 | 57 | **1** |
| langues distinctes OL, médiane | 9 | 16 | 5 | **1** |
| éditions OL sans langue taguée | 18 % | 17 % | 18 % | 13 % |
| œuvres avec édition **fr** dans OL | 97 % | 87 % | 60 % | 13 % |
| œuvres avec édition **en** dans OL | 83 % | 93 % | 70 % | 23 % |
| œuvres avec édition **es** dans OL | 73 % | 87 % | 90 % | 3 % |
| œuvres avec édition **ar** dans OL | **7 %** | **33 %** | 17 % | 60 % |
| éditions Wikidata (P629), médiane | 8 | 13,5 | 1 | 0 |
| notices Index UNESCO, médiane | 10 | 16,5 | 2,5 | 0* |

Trois enseignements :

**Open Library est le gisement principal, et de loin.** Wikidata (P629) trouve
une édition quand OL en trouve vingt — P629 sert de **lien qualifié** (avec le
traducteur, P655), pas d'inventaire. À l'inverse, 13 à 18 % des éditions OL
n'ont pas de langue taguée : la couverture réelle est un peu meilleure que
mesurée, mais il faudra inférer la langue (par l'éditeur ou le titre).

**Le passage vers l'arabe est le maillon faible dans les deux sens.** 7 % des
grandes œuvres françaises ont une édition arabe dans OL — alors que la
traduction existe presque toujours en réalité. C'est le miroir exact du
constat des séries : le contenu existe, la *donnée* n'existe pas.

**\* Le 0 % UNESCO du corpus arabe est un artefact d'écriture, pas une
absence.** L'Index translittère les titres arabes : la recherche en graphie
arabe ne trouve rien, mais « Mawsim al-hijra » ramène 4 notices, « Awlād
Hāratinā » 7. La jointure devra passer par la romanisation ou par l'auteur.
Sur l'ensemble de l'Index (829 377 notices) : 101 958 mentionnent le
français, 69 279 l'espagnol, 65 714 l'anglais, **5 226 l'arabe** — l'Index
documente surtout les flux *entre* langues européennes, et s'arrête en 2008.
C'est une **amorce historique**, pas un flux vivant.

## Volet 3 — Matière à notation : peut-on noter les 6 axes ?

Le critère de l'étude arabe des séries, réutilisé tel quel : ≥ 2 000
caractères cumulés (articles Wikipédia + description OL).

| Indicateur | fr | en | es | ar |
|---|---|---|---|---|
| article Wikipédia fr | 100 % | 100 % | 100 % | 87 % |
| article Wikipédia ar | 100 % | 100 % | 87 % | 100 % |
| longueur wp, langue d'origine (méd.) | 28 301 | 33 772 | 14 853 | 4 525 |
| description OL (méd.) | 315 | 656 | 232 | 0 |
| **notable (≥ 2 000 car.)** | **100 %** | **100 %** | **100 %** | **100 %** |

### Le verdict le plus important de l'étude

**Là où les séries arabes étaient notables à 22 %, les livres arabes du haut
du catalogue le sont à 100 %.** Un livre qui compte a un article Wikipédia —
souvent dans plusieurs langues — là où une série de Ramadan n'a qu'un synopsis
de 144 caractères. La chaîne d'enrichissement existante (Wikidata → sitelinks
→ Wikipédia) suffit à nourrir la notation, sans source supplémentaire. Ce
chiffre baissera dans la traîne, mais le point de départ est incomparablement
meilleur.

## Volet 4 — Procurabilité

| Indicateur | fr | en | es | ar |
|---|---|---|---|---|
| ISBN d'une édition fr | 97 % | 80 % | 50 % | 10 % |
| ISBN d'une édition ar | 0 % | 27 % | 10 % | 37 % |
| présente à la BnF | 100 % | 100 % | 97 % | 73 % |

L'ISBN est la clé : une fois l'édition connue dans la bonne langue, le lien
d'achat est un gabarit d'URL par pays (leslibraires.fr / placedeslibraires en
France, todostuslibros.com en Espagne, Bookshop.org en anglophonie — tous
interrogeables par ISBN, sans accord préalable pour un simple lien sortant).
La **BnF via SRU** s'avère un excellent filet pour le marché français : elle
trouve même 73 % du corpus arabe (traductions françaises cataloguées). Le
manque, encore lui : l'ISBN des éditions *arabes* (37 % dans le meilleur
corpus) — c'est le même trou que les éditions OL du volet 2, et il a le même
remède (§6).

---

## §5 — Ce qui se branche sur le pipeline, et où

Rien ne contredit `architecture-sourcing.md` ; le document anticipe même le
cas (« le flux hors-TMDB entrera par le pivot `oeuvre` »).

| Maillon existant | Équivalent livre |
|---|---|
| export quotidien TMDB → `tmdb_catalog` | **dump mensuel Open Library** (works + éditions, ~25 Go décompressés) → base de sondage |
| `popularity` TMDB | à dériver : sitelinks Wikidata + nb d'éditions OL + pages vues Wikipédia |
| collecte fiche + saisons (`parties=True`) | collecte **work + éditions** — les éditions par langue occupent la place des saisons |
| enrichissement `P4983 → Wikidata → sitelinks → Wikipédia` | identique, entrée par **P648** ou par QID — `WikidataClient` est déjà paramétré |
| crawler des séries hors TMDB (flux 2) | le même, sur « œuvre littéraire » — pour les 17 % arabes hors OL |
| TVmaze | rien (comme les films) ; UNESCO et BnF entrent en `riche_source` comme sources d'enrichissement |
| `facts` canonique (`normalize.py`) | clés en plus : `langue_originale`, `traducteur`, `editions[]` {langue, isbn, éditeur, année}, `oeuvre_originale` |

La seule vraie décision d'architecture : `univers.py` paramètre aujourd'hui
des détails *TMDB* (fichier d'export, segment d'URL). L'univers livre soit
généralise la dataclass (la source de référence devient un paramètre), soit
assume que son flux principal *est* le crawler. À trancher au moment du code,
pas avant.

## §6 — Combler l'angle mort arabe : les sources fermées

Le déficit arabe (éditions, ISBN, traductions *vers* l'arabe) ne se comble pas
avec les sources ouvertes mesurées ici. Trois pistes, par ordre de rendement :

**1. Arabic Union Catalog (الفهرس العربي الموحد) — la vraie réponse, à
négocier.** ~2,5 M de notices uniques, 5 000 bibliothèques de 27 pays, plus
d'un million d'entrées d'autorité (dont 500 000 noms de personnes — précieux
pour réconcilier les auteurs translittérés). L'accès public répond 403 :
c'est un service à adhésion, porté par la Bibliothèque du Roi Abdulaziz
(Riyad). La voie d'entrée est une **adhésion ou un partenariat de recherche**,
pas une API à découvrir. À chiffrer avant d'en dépendre ; en attendant, le
crawler Wikidata couvre le noyau.

**2. La jointure UNESCO par romanisation.** L'Index contient les classiques
arabes sous graphie latine (mesuré ci-dessus). Une table de correspondance
QID → titre romanisé (Wikidata porte souvent les deux) + l'auteur suffit à
récupérer l'historique des traductions — y compris *depuis* l'arabe vers les
langues cibles, ce que l'étude bibliométrique 1979–2012 du même Index a déjà
exploité.

**3. Les marchands arabes comme signal de disponibilité** (Jamalon,
Neelwafurat) : pas d'API publique, du scraping fragile — à ne considérer que
si le besoin « où l'acheter en arabe » devient réel, et plutôt sous forme de
lien de recherche par titre que de données collectées.

Pour le commercial fr/es (Dilicom/FEL, Electre, DILVE, l'API CEGAL de
todostuslibros) : tous à accès professionnel, tous négociables — et
probablement **inutiles pour un site de suggestion**, qui a besoin d'un lien
qui marche, pas d'un état de stock.

## Verdict

1. **Open Library comme première référence** de l'univers livre : le
   raccordement tient (77–100 % hors arabe), les éditions par langue donnent
   les traductions, les dumps donnent la base de sondage. Ses trous (18 %
   d'éditions sans langue, doublons de works) sont des défauts de qualité,
   pas de structure.
2. **La chaîne d'enrichissement existante suffit à la notation** — 100 % de
   notabilité sur les quatre corpus de tête, y compris l'arabe. C'est
   l'inverse du constat des séries, et c'est la meilleure nouvelle de
   l'étude.
3. **Les traductions se composent** : OL pour le volume, P629/P655 pour le
   lien qualifié, UNESCO (par romanisation) pour l'historique, BnF pour le
   référentiel français.
4. **L'arabe reste l'angle mort**, côté éditions et ISBN plutôt que côté
   matière. Court terme : crawler Wikidata + jointure UNESCO romanisée.
   Moyen terme : approcher l'Arabic Union Catalog.
