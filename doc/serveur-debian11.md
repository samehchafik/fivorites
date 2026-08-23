# Mise en place du serveur — Debian 11

> Postgres sur l'hôte, application en conteneur. À exécuter une fois, sur un
> Debian 11 (bullseye) frais. Une fois le serveur en place, le quotidien —
> lancer une passe, la surveiller, diagnostiquer une panne — est dans
> [`exploitation.md`](exploitation.md).
>
> L'ordre compte : le réseau Docker est créé **avant** de configurer Postgres,
> parce que c'est lui qui fait apparaître sur l'hôte l'adresse que Postgres doit
> écouter.

## 1. Installer PostgreSQL 16

Les dépôts Debian 11 ne proposent que **PostgreSQL 13**. Le poste de dev tourne
sur 16 : un écart de version majeure entre dev et serveur est exactement le
genre de détail qui ne se voit qu'en production. On passe donc par le dépôt
officiel PGDG.

```bash
sudo apt update && sudo apt install -y curl ca-certificates
```

```bash
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -fsSo /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
```

```bash
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bullseye-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
```

```bash
sudo apt update && sudo apt install -y postgresql-16
```

Vérification — le cluster `16 main` doit être `online` :

```bash
pg_lsclusters
```

## 2. Créer le rôle et la base

Génère un mot de passe et garde-le, il ira dans le `.env` du dépôt.

En hexadécimal, pas en base64 : le mot de passe est inséré dans une URL de
connexion (`postgresql://user:MOT_DE_PASSE@…`), et les `/` et `+` que produit
base64 y sont des caractères réservés — la connexion échouerait de façon
parfaitement obscure.

```bash
openssl rand -hex 32
```

Puis, en remplaçant `LE_MOT_DE_PASSE` :

```bash
sudo -u postgres psql -c "create role fivorites_v2 with login password 'LE_MOT_DE_PASSE'"
```

```bash
sudo -u postgres createdb --owner=fivorites_v2 fivorites_v2
```

Le schéma `sourcing` et ses tables ne se créent pas à la main : c'est le rôle
des migrations, à l'étape 5.

## 3. Installer Docker et créer le réseau

Le plugin `compose` n'est pas dans les dépôts Debian 11 — il vient du dépôt
officiel Docker.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
```

```bash
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg && sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bullseye stable" | sudo tee /etc/apt/sources.list.d/docker.list
```

```bash
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git
```

Récupère le dépôt :

```bash
sudo git clone <URL_DU_DEPOT> /srv/fivorites-v2 && sudo chown -R "$USER" /srv/fivorites-v2
```

Puis prépare le `.env`. **Il y en a deux dans le dépôt, à ne pas confondre :**

| Fichier | Pour quoi | Lu par |
|---|---|---|
| `.env` à la racine | le déploiement serveur | `docker-compose.yml` |
| `sourcing/.env` | le poste de dev | `fiv-sourcing` lancé en local |

Sur le serveur, c'est celui de la racine — `sourcing/.env` n'a aucun rôle ici,
les valeurs arrivent au conteneur par les variables du compose.

```bash
cd /srv/fivorites-v2 && cp .env.example .env
```

Renseigne dedans `DB_PASSWORD` (celui de l'étape 2) et `TMDB_BEARER`. `.env`
n'est pas versionné, seul `.env.example` l'est.

Construis l'image, puis crée le conteneur — c'est cette dernière commande qui
crée le réseau et fait apparaître `172.28.0.1` sur l'hôte :

```bash
sudo docker compose build sourcing
```

```bash
sudo docker compose --profile cli create sourcing
```

Contrôle :

```bash
ip -4 addr show | grep 172.28.0.1
```

## 4. Ouvrir l'accès Postgres depuis les conteneurs

L'application est en conteneur, la base sur l'hôte : Postgres doit écouter sur
la passerelle du réseau Docker. Le `docker-compose.yml` fige ce réseau sur
`172.28.0.0/16` — sans ça Docker en choisirait un au hasard et il faudrait
reprendre cette configuration à chaque recréation du réseau.

On n'ouvre que cette adresse : ni `0.0.0.0`, ni l'interface publique.

```bash
sudo -u postgres psql -c "alter system set listen_addresses = 'localhost,172.28.0.1'"
```

Puis autoriser le sous-réseau, avec mot de passe chiffré (`scram-sha-256`, le
défaut depuis PostgreSQL 14) :

```bash
echo "host    fivorites_v2    fivorites_v2    172.28.0.0/16    scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
```

```bash
sudo systemctl restart postgresql@16-main
```

La ligne est volontairement étroite : une seule base, un seul rôle, un seul
sous-réseau. Tout le reste continue de passer par `peer` en socket Unix locale.

Contrôle — les deux adresses doivent apparaître :

```bash
sudo ss -lntp | grep 5432
```

### Le pare-feu de l'hôte

**C'est l'étape qu'on oublie**, parce qu'on suppose que Docker s'en occupe. Il
ne s'en occupe pas : Docker programme les chaînes FORWARD et NAT, mais le
trafic d'un conteneur **vers l'hôte lui-même** arrive dans la chaîne INPUT, à
laquelle il ne touche pas. Sur un serveur dont la politique INPUT est en DROP —
le cas courant chez les hébergeurs — les paquets sont jetés en silence.

La signature est reconnaissable : `ConnectionTimeout` et non
`connection refused`. Un refus voudrait dire « personne n'écoute » ; un délai
dépassé veut dire « quelque chose mange les paquets ».

```bash
sudo iptables -S INPUT | head
```

Si tu vois `-P INPUT DROP` sans règle pour `172.28.0.0/16`, ouvre-la :

```bash
sudo iptables -I INPUT -s 172.28.0.0/16 -p tcp --dport 5432 -j ACCEPT
```

Les règles iptables ne survivent pas au redémarrage. À rendre persistant :

```bash
sudo apt install -y iptables-persistent && sudo netfilter-persistent save
```

Si tu utilises ufw plutôt qu'iptables nu :

```bash
sudo ufw allow from 172.28.0.0/16 to any port 5432 proto tcp
```

Dans les deux cas l'ouverture reste étroite : un sous-réseau privé, un port. La
base n'est jamais jointe depuis l'extérieur.

### Exposer ES et Neo4j à des IP fixes

Les deux services publient leurs ports sur `127.0.0.1` par défaut. Ça suffit
pour les joindre depuis un poste, **sans rien ouvrir** :

```bash
ssh -L 9200:127.0.0.1:9200 -L 7474:127.0.0.1:7474 -L 7687:127.0.0.1:7687 serveur
```

Le navigateur Neo4j répond alors sur `http://127.0.0.1:7474`. Les deux ports de
Neo4j sont nécessaires : la page est servie en 7474, mais c'est le navigateur du
poste qui ouvre la session Bolt en 7687.

**C'est la solution recommandée**, et pas par prudence de principe : ES tourne
ici **sans aucune authentification** (`xpack.security.enabled: false`), et Neo4j
parle en clair. Le tunnel les laisse tels quels, chiffrés par SSH, sans une
règle de pare-feu à écrire.

Si l'ouverture directe est vraiment nécessaire, il faut **deux** choses, et la
première seule ne protège rien :

```bash
# 1. L'interface d'écoute, dans .env à côté du compose
ES_BIND=0.0.0.0
NEO4J_BIND=0.0.0.0
```

```bash
sudo docker compose up -d elasticsearch neo4j
```

**Ça ne filtre pas la source** — ça dit seulement sur quelle interface de
l'hôte le port écoute. Et voici le piège, différent de celui de la chaîne INPUT
plus haut :

> **`ufw` et `iptables -A INPUT` ne protègent PAS un port publié par Docker.**
> Docker fait la traduction d'adresse dans la table `nat`, en `PREROUTING` :
> les paquets sont détournés **avant** d'atteindre `INPUT`. La règle est écrite,
> `ufw status` la montre, et elle ne sert à rien.

La chaîne qui mord est `DOCKER-USER`, que Docker place en tête de `FORWARD` et
ne réécrit jamais. Un détail de plus : à ce point les paquets ont déjà subi la
traduction d'adresse, donc `--dport` désigne le port **du conteneur**. Pour
viser le port publié, il faut `conntrack` :

```bash
IF=$(ip route get 1.1.1.1 | awk '{print $5; exit}')   # l'interface externe réelle
AUTORISEE=203.0.113.7                                  # l'IP fixe du poste
PORTS="9200 7475 7688"                                 # ceux PUBLIÉS, pas ceux des conteneurs

# `-I`, jamais `-A` : la chaîne DOCKER-USER se termine par un `RETURN`, et une
# règle ajoutée après lui n'est jamais lue. C'est l'erreur qui donne un
# pare-feu muet — les règles sont là, `iptables -S` les montre, elles ne
# servent à rien.
for PORT in $PORTS; do
  sudo iptables -I DOCKER-USER 1 -i "$IF" -p tcp -m conntrack --ctorigdstport $PORT -j DROP
  sudo iptables -I DOCKER-USER 1 -i "$IF" -p tcp -m conntrack --ctorigdstport $PORT \
       -s "$AUTORISEE" -j ACCEPT
done
# En tête de chaîne, donc inséré en dernier : sans lui, les réponses aux
# requêtes SORTANTES des conteneurs se font jeter.
sudo iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

sudo iptables -S DOCKER-USER     # relire l'ordre obtenu avant de sauver
sudo netfilter-persistent save
```

Les ports à lister sont ceux **publiés côté hôte**, pas ceux des conteneurs :
si `NEO4J_HTTP_PORT`/`NEO4J_BOLT_PORT` ont été décalés (§ cohabitation dans
[`graphe-neo4j.md`](graphe-neo4j.md)), ce sont les valeurs décalées qui comptent.

L'ordre final doit être : `ESTABLISHED,RELATED` en premier, puis pour chaque
port son `ACCEPT` **avant** son `DROP`. Pour plusieurs adresses, une ligne
`ACCEPT` de plus par adresse — `! -s` répété ne marche pas, chaque règle
rejetterait ce que l'autre autorise.

⚠ **Ces règles ne protègent que les conteneurs.** Un service qui tourne
directement sur l'hôte — c'est le cas du Neo4j installé sur cette machine, qui
écoute sur `*:7474` et `*:7687` — passe par `INPUT`, pas par `FORWARD`, et
n'est pas concerné par une seule ligne de ce qui précède. Le fermer demande une
règle `INPUT` séparée, et de vérifier d'abord qui s'en sert.

Contrôle, depuis une machine qui n'est pas dans la liste :

```bash
curl -m 5 http://<serveur>:9200/     # doit expirer, pas répondre
```

Et ce que ça ne règle toujours pas : **le trafic reste en clair**. L'IP fixe
protège de qui se connecte, pas de qui écoute sur le chemin. Le mot de passe
Neo4j part en base64 dans chaque en-tête, et ES n'en demande aucun. Avant
d'ouvrir pour de bon :

- **ES** : activer `xpack.security.enabled: true`, ce qui impose des comptes et
  une reconfiguration de `ES_URL` côté `admin` — ce n'est pas une case à cocher ;
- **Neo4j** : mettre du TLS (`server.https.enabled`) ou un proxy TLS devant ;
- **ou** : ne rien ouvrir et garder le tunnel, qui fait déjà tout ça.

## 5. Créer le schéma et vérifier

```bash
sudo docker compose run --rm sourcing db migrate
```

```bash
sudo docker compose run --rm sourcing doctor
```

`doctor` doit afficher :

```
✓  interpréteur       3.12.x — image, pas de vendor/
✓  identifiants TMDB  token v4
✓  base               PostgreSQL 16.x
✓  migrations         à jour
✓  schéma             sourcing — 5 table(s)
```

Si la ligne `base` échoue, le message dit lequel des deux cas s'applique :

| Message | Cause | Où regarder |
|---|---|---|
| `connection refused` | personne n'écoute sur l'adresse | `listen_addresses`, redémarrage de Postgres |
| `ConnectionTimeout` | les paquets sont jetés | la chaîne INPUT du pare-feu |
| `no pg_hba.conf entry` | on écoute, mais on refuse ce client | la ligne ajoutée à `pg_hba.conf` |

Pour isoler le réseau de l'application — un test TCP nu, sans Postgres ni
`fiv-sourcing` :

```bash
sudo docker compose run --rm --entrypoint python sourcing -c 'import socket; socket.create_connection(("172.28.0.1", 5432), 5); print("TCP OK")'
```

## 6. Utilisation courante

D'abord l'inventaire — un fichier public, aucune clé, aucun quota consommé :

```bash
sudo docker compose run --rm sourcing tmdb export
```

```bash
sudo docker compose run --rm sourcing tmdb catalog
```

Puis la collecte. `backfill` prend tout le catalogue et reprend là où la passe
précédente s'est arrêtée ; `--dry-run` compte le reste à faire sans rien
télécharger, `--limit` borne une passe d'essai :

```bash
sudo docker compose run --rm sourcing tmdb backfill --dry-run
```

```bash
sudo docker compose run --rm sourcing tmdb backfill --limit 200
```

Une série seule, et ce qu'il y a en base :

```bash
sudo docker compose run --rm sourcing tmdb fetch --id 1399
```

```bash
sudo docker compose run --rm sourcing tmdb stats
```

Les sources tierces s'ajoutent séparément, et **sans jeton TMDB** — l'entrée
dans Wikidata se fait par l'id qu'on a déjà. Une série d'abord, pour voir :

```bash
sudo docker compose run --rm sourcing enrich --id 1399
```

Puis tout ce qui n'a pas encore de complément. Compter d'abord, la passe
complète dure une trentaine d'heures :

```bash
sudo docker compose run --rm sourcing enrich --dry-run
```

```bash
sudo docker compose run --rm sourcing enrich --limit 500 --order random
```

```bash
sudo docker compose run --rm sourcing enrich
```

Elle s'interrompt et reprend comme `backfill` : un seul Ctrl-C, ou
`docker stop`, et relancer la même commande repart d'où l'on s'était arrêté.

Après une collecte, recopiez les dates de diffusion dans l'inventaire — c'est
ce qui alimente `enrich --order recent`, et ça ne demande aucun réseau :

```bash
sudo docker compose run --rm sourcing tmdb dates
```

Enfin le rattrapage : `tmdb changes` marque les séries que TMDB signale comme
modifiées, et le `backfill` suivant les recollecte.

```bash
sudo docker compose run --rm sourcing tmdb changes --days 1
```

Il n'y a pas de `docker compose up` : le sourcing est un pipeline par lots, pas
un service permanent. Pour le faire tourner régulièrement, ce sera une entrée de
crontab sur l'hôte — pas un conteneur qui boucle. La V1 tournait en
`while true; sleep 1`, ce qui rendait impossible de dire si le pipeline avançait
ou tournait à vide.

Pour éviter `sudo` sur chaque commande Docker :

```bash
sudo usermod -aG docker "$USER"   # puis se reconnecter
```

## 7. Le front d'administration

Contrairement au sourcing, c'est un **service permanent** : il répond en HTTP.
Deux sortes de requêtes, et le partage est net —

| Requête | Traitée par |
|---|---|
| `/api/*` | FastAPI, dans le conteneur `admin` |
| tout le reste | un fichier de `./www`, monté en volume |

Le front n'est pas dans l'image. Trois répertoires, et il vaut mieux ne pas
confondre les deux derniers :

| Répertoire | Contenu |
|---|---|
| `admin/` | l'API — c'est elle qui est dans l'image |
| `front/` | les **sources** du front, jamais montées en production |
| `www/` | le **répertoire statique** — `index.html` et ses fichiers, rien d'autre |

`www/` est **versionné** : il est construit sur le poste de dev et arrive par
`git pull`. Il n'y a donc pas de Node sur le serveur, et redéployer le front ne
demande **ni build, ni rebuild d'image**.

Le secret de session d'abord — sans lui le compose refuse de démarrer :

```bash
echo "ADMIN_SECRET_KEY=$(openssl rand -hex 32)" >> .env
```

Le schéma `admin` (il ajoute aussi les index de lecture sur `sourcing`, donc
`sourcing db migrate` doit être passé avant) :

```bash
sudo docker compose run --rm admin db migrate
```

Le front est déjà là : il est arrivé avec le `git pull`. Vérification —
trois fichiers, toujours les mêmes :

```bash
ls www www/assets
```

**Rien à construire sur le serveur**, et il n'existe aucun service pour le
faire : `www/` est versionné, le build se fait sur le poste de dev et se
commite. Si `www/` a été créé par Docker avant le premier `git pull`, il
appartient à root et bloque la mise à jour :

```bash
sudo rm -rf www && git pull
```

### Le dépôt du serveur ne doit jamais avoir de modification locale

C'est une copie de déploiement, pas un plan de travail. Un `git pull` qui
échoue en cours de route — droits, disque plein — laisse des fichiers à moitié
écrits que git compte ensuite comme des « modifications locales », et le pull
suivant refuse de démarrer. Rien n'a été modifié : la copie est simplement
restée entre deux états.

La remise à plat, qui **écrase tout ce qui est local** :

```bash
sudo chown -R "$USER" ~/fivorites && git fetch origin && git reset --hard origin/main
```

Pour voir ce qui diffère avant de l'écraser, si le doute existe :

```bash
git status --short && git diff --stat
```

Un compte — le mot de passe est demandé à l'invite, jamais passé en argument,
sans quoi il finirait dans l'historique du shell. `-it` est nécessaire pour que
l'invite fonctionne :

```bash
sudo docker compose run --rm -it admin user add sameh --name "Sameh"
```

Puis le service :

```bash
sudo docker compose up -d admin
sudo docker compose run --rm admin doctor
```

`doctor` doit afficher :

```
✓  interpréteur         3.12.x — image, pas de vendor/
✓  secret de session    configuré
✓  base                 postgresql://fivorites_v2:***@172.28.0.1:5432/fivorites_v2
✓  schéma sourcing      présent
✓  schéma admin         présent
✓  comptes              1
✓  catalogue            228 454 séries
✓  front construit      /srv/www
```

Le port est publié sur `0.0.0.0` par défaut : l'administration répond sur
`http://<serveur>:8182`, directement.

Ce qui circule alors en clair sur le réseau : le mot de passe saisi dans le
formulaire, et le cookie de session à chaque requête. C'est acceptable le temps
de la mise en route ; ça ne l'est plus quand la base contient des données ou que
le service reste en ligne.

Le jour où un reverse proxy TLS est devant (nginx, Caddy), deux lignes dans
`.env` referment tout :

```bash
ADMIN_BIND=127.0.0.1        # plus joignable que depuis la machine
ADMIN_COOKIE_SECURE=true    # le cookie refuse de circuler hors HTTPS
```

Avec `ADMIN_BIND=127.0.0.1`, l'accès se fait par un tunnel — rien à installer
sur le serveur :

```bash
ssh -L 8182:127.0.0.1:8182 serveur
```

### Après une collecte

La grille de cartes lit une projection (`admin.tv_card`), pas le brut — trier
228 000 séries sur une date qui vit dans un `jsonb` de plusieurs centaines de
kilooctets décompresserait toute la table à chaque page. À recalculer donc après
chaque passe :

```bash
sudo docker compose run --rm admin catalog refresh
```

Le front le signale de lui-même quand la projection est en retard, et un bouton
y fait la même chose. La fiche d'une série, elle, relit toujours le brut : ce
qu'on ouvre n'est jamais périmé.

### Mettre à jour

⚠️ **Les migrations sont dans l'image, pas sur le disque.** Les deux
`Dockerfile` font `COPY migrations ./migrations` et pointent `MIGRATIONS_DIR`
dedans ; aucun volume ne les monte. Un `git pull` amène donc le fichier `.sql`
sur le serveur **sans que le conteneur le voie** — et `db migrate` répond
tranquillement « base déjà à jour » alors qu'une migration attend. Toute
migration nouvelle impose de **reconstruire l'image avant de l'appliquer**.

```bash
git pull                                        # amène aussi le front déjà construit
```

Puis, pour chaque service dont `src/` **ou** `migrations/` a bougé :

```bash
sudo docker compose build sourcing
sudo docker compose run --rm sourcing db migrate
```

```bash
sudo docker compose build admin
sudo docker compose run --rm admin db migrate
sudo docker compose up -d admin
```

```bash
sudo docker compose build webapp
sudo docker compose run --rm webapp db migrate
sudo docker compose up -d webapp
```

Pour savoir ce que le `git pull` a réellement changé, et donc ce qu'il faut
reconstruire :

```bash
git diff --name-only HEAD@{1} HEAD | cut -d/ -f1,2 | sort -u
```

Contrôle — ce que l'image embarque vraiment, à comparer au dépôt :

```bash
sudo docker compose run --rm --entrypoint ls sourcing /app/migrations
```

`db migrate` n'applique que ce qui manque et le dit ; le relancer sur une base à
jour ne fait rien. **Il n'y a pas de base de test sur le serveur** : les images
ne contiennent ni `tests/`, ni `Makefile` — seulement `src`, `migrations` et le
point d'entrée. Les cibles `make` du dépôt (`test`, `db-create`, `db-drop-test`)
n'existent que sur le poste de développement, où Postgres et les toolchains sont
installés sur la machine.

Les fronts seuls ne demandent rien de plus que le `git pull` : les conteneurs
lisent `www/` et `www-site/` à chaque requête, il n'y a même pas à les
redémarrer.

**Une collecte en cours n'a pas à être arrêtée pour ça.** `sourcing` et `admin`
sont deux conteneurs distincts ; mettre à jour l'un ne touche pas l'autre. Le
seul cas qui l'exigerait est une migration ajoutant un index sur les tables de
`sourcing` — un `create index` prend un verrou qui bloque les écritures, donc
la collecte, le temps de sa construction. Le `git diff` ci-dessus dit s'il y en
a une.

### Arrêter et reprendre une collecte

Il n'y a pas d'état à sauvegarder : `backfill` recalcule sa liste à chaque
lancement depuis `fetch_state`. **Relancer la même commande reprend où l'on
s'était arrêté.**

En premier plan, un seul **Ctrl-C** — pas deux. Le premier arme un arrêt
propre : les collectes en vol vont à leur terme, les suivantes ne démarrent
pas. Le second tuerait le processus au milieu d'une série.

Depuis un autre terminal, ou si la commande a été lancée détachée :

```bash
sudo docker ps --filter name=sourcing --format '{{.Names}}'
```

```bash
sudo docker stop <le-nom-du-conteneur>
```

`docker stop` envoie SIGTERM, que `backfill` intercepte de la même façon. Le
compose lui laisse trois minutes (`stop_grace_period`) : le défaut de Docker est
de dix secondes, et une série de huit saisons en cinq langues représente
quarante requêtes — la couper au milieu laisse des saisons manquantes que la
reprise ne rattrapera pas, faute de les voir.

Puis, pour reprendre :

```bash
sudo docker compose run --rm sourcing tmdb backfill
```

## 8. Le site public

Le pendant public de l'administration : un service permanent lui aussi, sur le
port **8183**, géré par le même compose. Le partage des requêtes est le même —

| Requête | Traitée par |
|---|---|
| `/api/public/*` | FastAPI, dans le conteneur `webapp` |
| tout le reste | un fichier de `./www-site`, monté en volume |

Et les trois répertoires se lisent comme ceux de l'admin :

| Répertoire | Contenu |
|---|---|
| `webapp/` | l'API publique — c'est elle qui est dans l'image |
| `site/` | les **sources** Astro du site, jamais montées en production |
| `www-site/` | le **répertoire statique** — le build versionné, arrivé par `git pull` |

Pas de Node sur le serveur, pas de build : `www-site/` se construit sur le
poste (`make -C site build`) et se commite avec le code — même contrat que
`www/`, mêmes précautions (un `www-site/` créé par Docker avant le premier
`git pull` appartient à root : `sudo rm -rf www-site && git pull`).

Le secret de session d'abord — sans lui le compose refuse de démarrer. À
choisir une fois et à garder : il signe les cookies des **visiteurs**, et le
changer déconnecte tout le monde de ses classements (« j'ai vu et aimé »,
« je veux voir »), qui sont tout ce que ces sessions possèdent :

```bash
echo "WEBAPP_SECRET_KEY=$(openssl rand -hex 32)" >> .env
```

Le schéma `visiteur` — sa table de signaux tient une clé étrangère sur
`sourcing.oeuvre`, donc `sourcing db migrate` doit être passé avant. Et comme
partout, les migrations sont **dans l'image** : construire d'abord.

```bash
sudo docker compose build webapp
sudo docker compose run --rm webapp db migrate
```

Puis le service, et sa vérification :

```bash
sudo docker compose up -d webapp
sudo docker compose run --rm webapp doctor
```

`doctor` doit afficher `base : OK`, `schéma visiteur : OK`, `site construit :
oui`.

Ce que le site exige du reste de la maison — rien au démarrage, tout à
l'usage :

* **la recherche** lit les index Elasticsearch de l'admin (`search reindex`,
  puis la passe nocturne). ES absent → repli SQL automatique, plus lent,
  titres originaux seulement ;
* **les suggestions** lisent le graphe Neo4j (`graphe schema`, `graphe
  projeter`, `graphe projeter-membres`) et exigent `NEO4J_PASSWORD` dans
  `.env`. Graphe absent → la route répond 503 en disant quoi faire, le reste
  du site vit normalement ;
* **les vignettes** lisent les projections `admin.*_card` (`catalog
  refresh`).

Sur l'exposition, la logique est **inverse de celle de l'admin** : ce site
est fait pour être public. `WEBAPP_BIND=0.0.0.0` (le défaut) convient à la
mise en route, mais la cible normale est un reverse proxy TLS (nginx, Caddy)
qui porte le nom de domaine et le certificat, avec :

```bash
WEBAPP_BIND=127.0.0.1       # seul le proxy local joint le conteneur
WEBAPP_COOKIE_SECURE=true   # le cookie de session refuse de circuler hors HTTPS
```

Le cookie transporte l'identité anonyme du visiteur ; en clair, il se vole
comme un cookie d'admin. Tant que le proxy n'est pas là, le site marche —
mais les classements des visiteurs voyagent en clair, et c'est une raison de
ne pas tarder.

### Mettre five.ifrit.fr devant (nginx + Let's Encrypt)

Le proxy est **nginx**, sur l'hôte (paquet apt, pas un service du compose),
avec un certificat Let's Encrypt obtenu par **certbot** en mode webroot et
renouvelé par **cron**. Deux fichiers versionnés portent tout :

| Fichier | Rôle |
|---|---|
| [`deploy/nginx-five.conf`](../deploy/nginx-five.conf) | le vhost — la source de vérité, copiée sur le serveur, jamais éditée sur place |
| [`deploy/install-five.sh`](../deploy/install-five.sh) | la mise en service complète, en une commande |

**Le seul prérequis manuel est le DNS** : un enregistrement `A` (et `AAAA` si
la machine a une IPv6) qui pointe `five.ifrit.fr` vers le serveur. Le script
refuse de démarrer tant qu'il ne résout pas — certbot échouerait de toute
façon.

Puis, depuis la racine du dépôt :

```bash
sudo FIVE_EMAIL=vous@exemple.fr ./deploy/install-five.sh
```

(l'adresse ne sert qu'à Let's Encrypt — les avis d'expiration du certificat.)

Ce que le script enchaîne, idempotent de bout en bout — le relancer après un
échec reprend où il en était :

1. **le service** : `WEBAPP_SECRET_KEY` généré s'il manque (jamais réécrit —
   il porte les classements des visiteurs), image construite, schéma
   `visiteur` migré, conteneur démarré et sondé ;
2. **nginx et certbot** installés par apt ;
3. **le pare-feu** : 80 et 443 ouverts dans ufw s'il est actif — AVANT le
   certificat, le défi ACME passe par 80. nginx est sur l'hôte : c'est le
   pare-feu ordinaire qui s'applique, pas la chaîne DOCKER-USER du §4 ;
4. **le certificat** : un vhost HTTP provisoire le temps du défi (le vhost
   TLS référence des fichiers que certbot n'a pas encore écrits, `nginx -t`
   refuserait), `certbot certonly --webroot`, puis le vhost définitif copié
   depuis `deploy/nginx-five.conf` et rechargé sans coupure ;
5. **le renouvellement** : `/etc/cron.d/five-certbot` — `certbot renew`
   deux fois par jour, qui ne touche à rien tant que le certificat a plus de
   trente jours, avec un `--deploy-hook` qui ne recharge nginx que si un
   certificat a réellement changé ;
6. **la fermeture** : une fois `https://five.ifrit.fr` vérifié — et
   seulement alors, sinon un ACME en échec laisserait le site injoignable —
   `WEBAPP_BIND=127.0.0.1` et `WEBAPP_COOKIE_SECURE=true` dans le `.env`,
   et le conteneur recréé (`up -d` : la publication du port fait partie de
   sa définition, un `restart` ne la changerait pas).

Le script termine sur son bilan : le code HTTP du site, la réponse de
`/api/public/health`, la redirection 301 du port 80, la date d'expiration du
certificat. À vérifier en plus depuis l'extérieur : `http://<serveur>:8183`
ne répond **plus** — c'est tout l'objet de `WEBAPP_BIND=127.0.0.1`.

L'admin n'est pas concernée par cette bascule : elle reste joignable en
direct sur `:8182` comme avant. Le jour où elle passe elle aussi derrière le
TLS, c'est un second vhost sur le même modèle (`proxy_pass` vers 8182) et les
deux lignes `ADMIN_BIND=127.0.0.1` + `ADMIN_COOKIE_SECURE=true` du §7.

## Sauvegarde

La base est sur l'hôte : pas de volume Docker à sauvegarder.

```bash
sudo -u postgres pg_dump --format=custom fivorites_v2 > "fivorites_v2_$(date +%F).dump"
```

Le contenu de `sourcing.raw_source` est re-téléchargeable, mais lentement — une
sauvegarde évite de repasser des jours d'appels TMDB.
