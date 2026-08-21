# fivorites

Suggestion d'éléments culturels — séries, films, livres, BD, musique.

Le principe : chaque membre publie ses **top 5** par univers, et le site lui suggère
des découvertes.

## V2

Réécriture complète. Le changement de fond par rapport à la V1 : ajouter une
**description vectorielle du contenu** à côté du graphe communautaire.

Chaque œuvre est résumée par **6 axes de goût** notés de 1 à 10, communs aux cinq
univers :

| Axe | 1 | 10 |
|---|---|---|
| Luminosité | noir, désespéré | lumineux, réparateur |
| Intensité | doux, apaisant | bouleversant, éprouvant |
| Humour | grave, premier degré | drôle, ironique |
| Exigence | immédiat, évident | dense, demande un effort |
| Étrangeté | familier, balisé | singulier, déroutant |
| Charge sensorielle | sobre, transparent | saturé, stylisé |

Ce socle commun permet trois choses que le graphe seul ne sait pas faire : traiter le
démarrage à froid, expliquer une suggestion, et suggérer d'un univers à l'autre
(d'une série vers un livre, d'un livre vers un album).

Les données sont organisées en trois couches :

1. **Faits** — objectifs, extraits des sources (dates, format, pays, personnes, lieux)
2. **Axes de goût** — les 6 notes, calibrées
3. **Facettes d'usage** — *déduites* des deux premières, jamais saisies

## État

L'acquisition des séries est en place : le catalogue TMDB est inventorié
(228 454 séries) et la collecte de masse tourne. La couche 2 — les axes — est
notée et estimée sur la traîne. Le graphe de recommandation vient de s'ouvrir :
les œuvres, leurs genres et leur distribution y entrent, et l'empreinte y est
indexée pour la recherche des plus proches voisins. Les facettes d'usage
restent à construire. **L'univers livres vient d'ouvrir** : sans TMDB, il
entre par le crawler Wikidata + Open Library (traductions par langue
d'édition), avec son onglet dans l'admin et ses index ES/graphe — voir
[`doc/etude-sources-livres.md`](doc/etude-sources-livres.md).

| Répertoire | Rôle |
|---|---|
| [`sourcing/`](sourcing) | la collecte : TMDB (séries, films), Wikidata + Open Library (livres), Wikipédia |
| [`admin/`](admin) | le front d'administration — ce qui est collecté, ce qui reste à faire |
| [`front/`](front) | les sources React de ce front |
| `www/` | le résultat du build, versionné : déployer le front, c'est `git pull` |

| Document | Rôle |
|---|---|
| [`doc/architecture-sourcing.md`](doc/architecture-sourcing.md) | **l'architecture cible du sourcing** — les règles, le JSON canonique, le chemin |
| [`doc/v2-acquisition-series.md`](doc/v2-acquisition-series.md) | le plan d'acquisition, les décisions et les lots |
| [`doc/serveur-debian11.md`](doc/serveur-debian11.md) | la mise en place du serveur, une fois pour toutes |
| [`doc/exploitation.md`](doc/exploitation.md) | lancer, surveiller, diagnostiquer — au quotidien |
| [`doc/admin.md`](doc/admin.md) | **l'administration** — où est le code, ce qu'il fait, ce qui a été construit |
| [`doc/contrat-donnees-admin.md`](doc/contrat-donnees-admin.md) | comment l'admin lit le sourcing — les langues, les nouvelles tables |
| [`doc/graphe-neo4j.md`](doc/graphe-neo4j.md) | **le graphe** — le modèle, les deux distances de l'empreinte, la mise en service |
| [`doc/dictionnaire-donnees.md`](doc/dictionnaire-donnees.md) | **la donnée en détail** — chaque table, chaque colonne, les payloads |
| [`doc/etude-couverture-marche-arabe.md`](doc/etude-couverture-marche-arabe.md) | ce que valent les catalogues arabe, golfe et turc |
| [`doc/etude-sources-complementaires.md`](doc/etude-sources-complementaires.md) | ce qu'apportent Wikidata et TVmaze — et pourquoi IMDb est écartée |
| [`doc/etude-sources-livres.md`](doc/etude-sources-livres.md) | l'univers livre — Open Library, Wikidata, UNESCO, BnF, et l'angle mort arabe |
