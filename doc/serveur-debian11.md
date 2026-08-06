# Mise en place du serveur — Debian 11

> Postgres sur l'hôte, application en conteneur. À exécuter une fois, sur un
> Debian 11 (bullseye) frais.
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
✓  schéma             sourcing — 2 table(s)
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

```bash
sudo docker compose run --rm sourcing tmdb fetch --id 1399
```

```bash
sudo docker compose run --rm sourcing tmdb stats
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

⚠️ **Ne pas lancer `www-build` sur le serveur.** Ce service existe pour le
dépannage, mais il tourne en root : il laisse `www/` inécrivable pour votre
compte, et le `git pull` suivant échoue sur
`cannot create directory at 'www/assets': Permission denied`. Si c'est déjà
arrivé, ou si Docker a créé `www/` avant le premier `git pull` :

```bash
sudo rm -rf www && git pull
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

```bash
git pull                                        # amène le front déjà construit
sudo docker compose build admin                 # seulement si admin/src a bougé
sudo docker compose run --rm admin db migrate   # seulement si admin/migrations a bougé
sudo docker compose up -d admin
```

Le front seul ne demande rien de plus que le `git pull` : le conteneur lit
`www/` à chaque requête, il n'y a même pas à le redémarrer.

**Une collecte en cours n'a pas à être arrêtée pour ça.** `sourcing` et `admin`
sont deux conteneurs distincts ; mettre à jour l'un ne touche pas l'autre. Le
seul cas qui l'exigerait est une migration ajoutant un index sur les tables de
`sourcing` — un `create index` prend un verrou qui bloque les écritures, donc
la collecte, le temps de sa construction.

Pour savoir ce qu'un `git pull` a réellement changé avant de décider :

```bash
git diff --name-only HEAD@{1} HEAD | cut -d/ -f1 | sort -u
```

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

## Sauvegarde

La base est sur l'hôte : pas de volume Docker à sauvegarder.

```bash
sudo -u postgres pg_dump --format=custom fivorites_v2 > "fivorites_v2_$(date +%F).dump"
```

Le contenu de `sourcing.raw_source` est re-téléchargeable, mais lentement — une
sauvegarde évite de repasser des jours d'appels TMDB.
