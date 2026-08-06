# Avancement — acquisition des séries

> Journal de ce qui a été construit, décidé et mesuré. Conçu pour être
> **auto-suffisant** : ouvrir un thread avec ce seul fichier doit suffire à
> reprendre le travail.
>
> Compléments : [`v2-acquisition-series.md`](v2-acquisition-series.md) pour le
> plan, [`serveur-debian11.md`](serveur-debian11.md) pour le déploiement,
> [`sourcing/README.md`](../sourcing/README.md) pour l'usage courant.
>
> Dernière mise à jour : 2026-08-05.

---

## 1. Où on en est

Le lot 1 (socle) et le lot 2 (catalogue et collecte de masse) sont livrés. Le
pipeline sait télécharger la liste complète des séries TMDB et les collecter
toutes, avec reprise sur incident.

**Un seul point bloque** : le jeton TMDB est refusé par l'API (HTTP 401). Rien
n'a donc encore été collecté sur le serveur. L'export du catalogue, lui,
fonctionne — il ne demande aucune authentification.

| | État |
|---|---|
| Poste de dev | opérationnel, catalogue de 228 454 séries chargé |
| Serveur Debian 11 | image construite, base migrée, jeton TMDB à corriger |
| Tests | 57 — 31 unitaires, 26 de bout en bout sur Postgres |
| Code | ~2 700 lignes de source, ~1 000 de tests |

---

## 2. Ce qui existe

### 2.1 Les commandes

```bash
fiv-sourcing doctor                    # interpréteur, base, migrations, schéma, jeton TMDB
fiv-sourcing db migrate                # applique les migrations manquantes

fiv-sourcing tmdb export               # charge la liste de toutes les séries
fiv-sourcing tmdb catalog              # volumétrie et répartition par popularité
fiv-sourcing tmdb fetch --id 1399      # collecte une série
fiv-sourcing tmdb backfill             # collecte tout le catalogue, reprenable
fiv-sourcing tmdb stats                # ce qui est en base + projection de volume
```

`backfill` accepte `--limit`, `--concurrency`, `--order`, `--refresh-after` et
`--dry-run`.

### 2.2 Le schéma

Une base — `fivorites_v2` — et un schéma par domaine.

| Table | Rôle |
|---|---|
| `sourcing.raw_source` | le brut, append-only, une ligne par réponse HTTP |
| `sourcing.fetch_state` | fraîcheur et état par objet ; remplace les 3 fichiers JSON de la V1 |
| `sourcing.tmdb_catalog` | inventaire du catalogue, issu de l'export quotidien |
| `public.schema_migrations` | historique des migrations, valable pour la base entière |

`catalog` (faits) et `scores` (axes) viendront aux lots 4 et suivants. La
connexion pose le `search_path`, donc le code écrit `raw_source` sans préfixe ;
les migrations qualifient tout explicitement.

### 2.3 Les invariants

**Une réponse HTTP = une ligne de `raw_source`.** C'est ce qui donne à chaque
saison sa propre fraîcheur, son propre statut et sa propre empreinte. Le
regroupement des saisons sous une série appartient à la dérivation. À la
question « pourquoi pas une colonne `saisons[]` » : parce qu'un tableau
imposerait de réécrire toute la série pour rafraîchir une saison, invaliderait
l'empreinte du bloc entier au moindre changement, et rendrait les échecs
tout-ou-rien.

**Rejouer une collecte inchangée n'écrit rien.** Déduplication par SHA-256 du
payload canonicalisé. C'est ce qui rend un rafraîchissement quotidien du
catalogue soutenable.

**Un 404 se conserve, un 401 non.** Le premier est un fait sur la source — « cet
id a disparu de TMDB ». Le second ne dit rien de l'œuvre, seulement de notre
configuration ; le stocker polluerait le brut d'autant de lignes que d'ids
tentés le jour où un jeton expire.

---

## 3. Décisions

| Sujet | Décision | Pourquoi |
|---|---|---|
| **Catalogue V1** | table rase | TMDB est re-collectable ; seuls les fives utilisateurs sont irremplaçables |
| **Filtrage à l'acquisition** | **aucun** | voir §5.2 — `popularity` écarterait les catalogues arabe et turc |
| **Tri du backfill** | `id` par défaut | trier par popularité serait un jugement implicite |
| **Langues des saisons** | fr, en, es, ar, tr | un appel par langue : c'est le seul moyen d'obtenir les synopsis d'épisode traduits |
| **Python** | 3.12 vendorisé dans `sourcing/vendor` | aucune dépendance à un interpréteur système |
| **Postgres** | toujours sur l'hôte, jamais en conteneur | dev comme serveur |
| **Docker** | serveur uniquement, pour l'application | le poste de dev n'en utilise pas |

---

## 4. Coût de la collecte

Par série : 1 appel pour la fiche (avec `translations`, donc toutes les langues
d'un coup) + 1 appel **par saison et par langue**. Une série de 8 saisons =
41 requêtes avec les cinq langues.

Sur 228 454 séries, l'ordre de grandeur est de **2 millions de requêtes**, soit
une trentaine d'heures à 20 req/s. Ce chiffre est une extrapolation, pas une
mesure — voir §7.

⚠️ **À vérifier avant d'engager la passe complète** : l'endpoint `translations`
d'une saison suffirait-il à remplacer les cinq appels ? Ma compréhension est
qu'il ne couvre que le nom et le synopsis *de la saison*, pas l'`overview` de
chaque épisode — mais si je me trompe, le coût des saisons est divisé par cinq.
Une seule requête suffit à trancher.

---

## 5. Ce qui a été mesuré

### 5.1 Volumétrie

**228 454 séries**, export du 2026-08-05, téléchargé et chargé en 4 secondes.
Le fichier est public : aucune clé, aucun quota consommé.

Répartition par décile de popularité :

| Décile | Séries | Popularité max | min |
|---|---|---|---|
| 1 | 22 846 | 406,44 | 3,71 |
| 2 | 22 846 | 3,71 | 2,28 |
| … | | | |
| 10 | 22 845 | 0,23 | 0,00 |

La falaise est brutale : le premier décile couvre 406 → 3,71, les neuf autres se
partagent 3,71 → 0.

| Popularité ≥ | Séries | Part |
|---|---|---|
| 1 | 110 437 | 48 % |
| 5 | 14 593 | 6,4 % |
| 10 | 5 059 | 2,2 % |
| 20 | 1 733 | 0,8 % |

### 5.2 ⭐ Pourquoi `popularity` ne peut pas servir de filtre

C'est la mesure la plus structurante du projet à ce stade.

`popularity` est une métrique d'usage **du site TMDB** — vues de fiche, votes,
watchlist. La base d'utilisateurs de TMDB est très majoritairement occidentale.
Répartition par système d'écriture du titre original :

| Écriture | Séries | Popularité médiane | % ≥ 5 |
|---|---|---|---|
| latin / autre | 166 753 | 0,89 | **6,3 %** |
| CJK | 49 839 | 1,11 | **7,4 %** |
| arabe | 5 560 | 1,10 | **1,0 %** |
| cyrillique | 4 762 | 1,33 | 3,6 % |
| indices turcs | 1 540 | 1,83 | 13,3 % |

**Un seuil à 5 retiendrait 54 des 5 560 séries en écriture arabe.** L'écriture
arabe pèse 2,4 % du catalogue et ne représenterait plus que 0,4 % du corpus —
une sous-représentation d'un facteur six.

Et les médianes sont comparables : ces séries ne sont pas « moins populaires »,
leur distribution n'a simplement pas de tête longue sur TMDB. Le public arabe
consulte peu TMDB ; la queue existe, le sommet manque.

Sur des titres nommés, le sommet passe mais le milieu de tableau tombe :

| Titre | Popularité | Seuil ≥ 5 |
|---|---|---|
| Muhteşem Yüzyıl | 20,85 | gardée |
| باب الحارة | 11,39 | gardée |
| Diriliş: Ertuğrul | 10,12 | gardée |
| **الاختيار** | **3,44** | **écartée** |

*Al-Ikhtiyar*, l'une des plus grosses productions égyptiennes récentes, tombe
sous le seuil.

⚠️ **Réserve sur ma propre mesure** : la détection du turc par `[ğışĞİŞ]` ne
capte que les titres contenant ces lettres — elle rate *Kara Sevda*, *Ezel*. Les
1 540 sont un plancher et les 13,3 % sont calculés sur un sous-échantillon
biaisé. La détection de l'écriture arabe, elle, est fiable : alphabet distinct.

**Conclusion** : aucun filtre à l'acquisition. On prend tout, l'utilisateur
décidera en aval sur des données complètes.

---

## 6. Défauts trouvés et corrigés

Utile pour ne pas les réintroduire.

### Hérités de la V1

- **`append_to_response` demandait `releases` et `lists`** — endpoints *films*,
  demandés sur des séries depuis 2017. Deux sous-requêtes pour rien.
- **`external_ids` absent** — sans lui, aucun raccordement possible à Wikidata
  ni Wikipédia, donc aucune couche géographique. Ajouté.
- **`id_tmdb` non stocké** — la ligne était commentée dans le ColumnSet V1.
  À corriger au lot 4, la colonne devra être unique et indexée.

### Introduits et corrigés pendant ce chantier

- **uv détruisait la venv vendorisée.** `UV_PYTHON_INSTALL_DIR` n'est pas une
  clé de `uv.toml` — uv ne la lit que dans l'environnement. Un `uv run` nu
  recréait la venv sur `~/.local/share/uv`, silencieusement. Trois verrous :
  le Makefile exporte la variable, aucune cible n'appelle `uv run`, et
  `make guard` échoue avant d'exécuter quoi que ce soit.
- **`migrate` réussissait sur un répertoire absent** — « 0 migration appliquée »
  et code de sortie 0, base vide, rien pour relier les deux. Erreur bruyante
  désormais.
- **L'image se construisait avec un module manquant** — la panne n'apparaissait
  qu'au premier lancement, après déploiement. Test de fumée ajouté au
  `Dockerfile` : tous les modules sont importés au build.
- **Les tests tournaient sur la base de travail et l'ont vidée** — 228 000
  séries perdues au premier `make test`. Base `_test` séparée depuis.
- **`doctor` ne validait pas le jeton TMDB** — il affichait « token v4 » pour
  toute variable non vide. Il fait maintenant un appel authentifié réel.
- **Mot de passe en base64 dans une URL de connexion** — les `/` et `+` y sont
  réservés. Le runbook impose `openssl rand -hex`.

### Vérifiés plutôt que supposés

- **Connexion psycopg partagée entre tâches concurrentes** : `cursor.execute`
  prend le verrou de la connexion, les écritures se sérialisent. Une seule
  connexion est correcte.
- **Ordre réseau Docker / Postgres** : `172.28.0.1` n'existe sur l'hôte
  qu'après création du réseau Docker. Le runbook crée le réseau avant de
  configurer `listen_addresses`.
- **Pare-feu** : Docker programme FORWARD et NAT, pas INPUT. Un conteneur qui
  joint l'hôte passe par INPUT, que Docker n'ouvre pas. Signature :
  `ConnectionTimeout` et non `connection refused`.

---

## 7. Questions ouvertes

Par ordre de ce qui bloque.

1. 🔴 **Le jeton TMDB est refusé** (HTTP 401). Un token v4 est un JWT : commence
   par `eyJ`, ~200 caractères, deux points. Une clé v3 (32 caractères
   hexadécimaux) va dans `TMDB_API_KEY`, pas `TMDB_BEARER`.
2. 🔴 **Licence TMDB.** L'API est libre en usage non commercial avec attribution ;
   un usage commercial demande leur accord. C'est le seul point qui pourrait
   invalider tout ce qui est construit. À lever **avant** la passe complète.
3. 🟠 **Volume disque.** Non mesuré. `tmdb backfill --limit 200` puis
   `tmdb stats` donne la projection, à comparer à `df -h`.
4. 🟠 **Débit toléré par TMDB.** La limite dure a été supprimée en 2019 ; ce qui
   subsiste n'est pas documenté. Le backfill compte les 429 et conclut. Défaut
   prudent : 20 req/s.
5. 🟠 **Écart de version Postgres** : 16.1 en dev, **13.23** sur le serveur — le
   dépôt PGDG du runbook n'a pas été utilisé. Rien de ce qui est écrit
   aujourd'hui n'exige plus que la 13, mais l'écart est à résorber avant que la
   base contienne des données coûteuses à re-collecter.
6. ⚠️ **`translations` sur les saisons** — cf. §4, facteur cinq sur le coût.
7. ⚠️ **Marchés visés.** Un catalogue équilibré fr / en / es / ar / tr n'a pas la
   même forme qu'un catalogue francophone avec des ouvertures. N'affecte pas
   l'acquisition (on prend tout), mais déterminera ce qu'on considère comme une
   couverture suffisante au lot 5.

---

## 8. Suite

| Lot | Contenu |
|---|---|
| 3 | Wikidata (P915 lieu de tournage, P840 lieu de l'action) et Wikipédia |
| 4 | Dérivation de la couche 1 : `catalog.series`, `id_tmdb` unique et indexé |
| 5 | **Rapport de couverture** — le vrai livrable : matière textuelle disponible par décile |
| 6 | Rafraîchissement incrémental via `/tv/changes` et priorités |

Le lot 5 est celui qui tranche le périmètre et le budget de notation. Il fournit
aussi le **constructeur de dossier de notation** : la fonction
`series_id → texte prêt à noter`, interface exacte entre acquisition et couche 2.

---

## 9. Commits

| Hash | Contenu |
|---|---|
| `46aa882` | mesure du plafond de débit TMDB |
| `c58a307` | catalogue complet et collecte de masse |
| `088f30b` | collecte des saisons en cinq langues |
| `b6027f5` et avant | socle, schéma, déploiement |
