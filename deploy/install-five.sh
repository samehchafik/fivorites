#!/usr/bin/env bash
# Mise en service de five.ifrit.fr — nginx, Let's Encrypt, et le site public.
#
# À lancer EN ROOT, depuis la racine du dépôt, sur le serveur Debian 11 :
#
#     sudo FIVE_EMAIL=vous@exemple.fr ./deploy/install-five.sh
#
# (l'adresse ne sert qu'à Let's Encrypt — les avis d'expiration du
# certificat ; elle n'apparaît nulle part ailleurs.)
#
# Idempotent : chaque étape vérifie avant d'agir, et relancer le script après
# un échec — DNS pas encore propagé, port fermé — reprend où il en était.
#
# Ce qu'il fait, dans l'ordre, et pourquoi cet ordre :
#
#   1. l'image webapp, sa migration (schéma visiteur), le service ;
#   2. nginx + certbot depuis apt ;
#   3. le pare-feu (80/443) AVANT le certificat — le défi ACME passe par 80 ;
#   4. le vhost HTTP seul, puis le certificat par webroot, puis le vhost TLS
#      versionné (deploy/nginx-five.conf) — l'ordre inverse ferait échouer
#      `nginx -t` sur un certificat qui n'existe pas encore ;
#   5. le cron de renouvellement (/etc/cron.d/five-certbot) ;
#   6. la fermeture du conteneur sur la boucle locale (WEBAPP_BIND=127.0.0.1,
#      WEBAPP_COOKIE_SECURE=true) — en DERNIER, une fois le HTTPS vérifié :
#      dans l'autre ordre, un ACME en échec laisserait le site injoignable.

set -euo pipefail

DOMAINE="five.ifrit.fr"
WEBROOT="/var/www/letsencrypt"
VHOST="/etc/nginx/sites-available/${DOMAINE}.conf"
CRON="/etc/cron.d/five-certbot"
EMAIL="${FIVE_EMAIL:-${1:-}}"

dire()   { printf '\n\033[1m— %s\033[0m\n' "$*"; }
erreur() { printf '\033[31mERREUR : %s\033[0m\n' "$*" >&2; exit 1; }

# --- Les gardes ---------------------------------------------------------------

[ "$(id -u)" = 0 ] || erreur "à lancer en root :  sudo FIVE_EMAIL=… ./deploy/install-five.sh"
[ -f docker-compose.yml ] && [ -f deploy/nginx-five.conf ] \
    || erreur "à lancer depuis la racine du dépôt (là où vit docker-compose.yml)"
[ -f .env ] || erreur "pas de .env à côté du compose — copier .env.example et le remplir d'abord"
command -v docker >/dev/null || erreur "docker absent — voir doc/serveur-debian11.md §3"
[ -f www-site/index.html ] \
    || erreur "www-site/index.html absent — le build versionné arrive par git pull (doc §8)"
[ -n "$EMAIL" ] \
    || erreur "adresse Let's Encrypt manquante :  sudo FIVE_EMAIL=vous@exemple.fr ./deploy/install-five.sh"

# Le DNS d'abord : certbot échouerait de toute façon, autant le dire en clair.
getent hosts "$DOMAINE" >/dev/null \
    || erreur "$DOMAINE ne résout pas — poser l'enregistrement A (et AAAA) vers ce serveur, attendre la propagation, relancer"

# --- 1. Le service webapp -----------------------------------------------------

# Le secret de session, généré UNE fois et jamais réécrit : il signe les
# cookies des visiteurs, et le changer efface leurs classements.
if ! grep -q '^WEBAPP_SECRET_KEY=.' .env; then
    dire "WEBAPP_SECRET_KEY absent du .env — génération"
    sed -i '/^WEBAPP_SECRET_KEY=$/d' .env
    echo "WEBAPP_SECRET_KEY=$(openssl rand -hex 32)" >> .env
fi

dire "l'image webapp, sa migration, le service"
docker compose build webapp
docker compose run --rm webapp db migrate
docker compose up -d webapp

printf 'attente de /api/public/health'
for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:8183/api/public/health >/dev/null 2>&1 && break
    printf '.'; sleep 1
done; echo
curl -fsS http://127.0.0.1:8183/api/public/health >/dev/null \
    || erreur "le service ne répond pas sur 8183 — voir  docker compose logs webapp"

# --- 2. nginx et certbot --------------------------------------------------------

dire "nginx et certbot (apt)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot

# --- 3. Le pare-feu, AVANT le certificat ---------------------------------------

# nginx tourne sur l'hôte : c'est le pare-feu ordinaire qui s'applique, pas la
# chaîne DOCKER-USER du §4 de la doc.
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    dire "ufw : 80 et 443"
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
fi

# --- 4. Le vhost HTTP, le certificat, le vhost TLS -----------------------------

mkdir -p "$WEBROOT"

# Phase 1 — HTTP seul, si le certificat n'existe pas encore : le vhost TLS
# versionné référence des fichiers que certbot n'a pas encore écrits, et
# `nginx -t` refuserait de servir le défi ACME.
if [ ! -f "/etc/letsencrypt/live/${DOMAINE}/fullchain.pem" ]; then
    dire "vhost HTTP provisoire (le temps du défi ACME)"
    cat > "$VHOST" <<PHASE1
# Provisoire — remplacé par deploy/nginx-five.conf dès le certificat obtenu.
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAINE};
    location /.well-known/acme-challenge/ { root ${WEBROOT}; }
    location / { return 503; }
}
PHASE1
    ln -sf "$VHOST" "/etc/nginx/sites-enabled/${DOMAINE}.conf"
    nginx -t
    systemctl reload nginx

    dire "certificat Let's Encrypt (webroot)"
    certbot certonly --webroot -w "$WEBROOT" -d "$DOMAINE" \
        -m "$EMAIL" --agree-tos --no-eff-email --non-interactive
else
    dire "certificat déjà présent — rien à demander"
fi

dire "vhost TLS (deploy/nginx-five.conf)"
cp deploy/nginx-five.conf "$VHOST"
ln -sf "$VHOST" "/etc/nginx/sites-enabled/${DOMAINE}.conf"
nginx -t
systemctl reload nginx

# --- 5. Le renouvellement ------------------------------------------------------

# `certbot renew` relit la conf de renouvellement écrite à l'obtention (mode
# webroot compris) et ne touche à rien tant que le certificat a plus de trente
# jours. Deux passages par jour à minute décalée, comme certbot le recommande ;
# le deploy-hook ne recharge nginx QUE si un certificat a vraiment changé.
dire "cron de renouvellement ($CRON)"
cat > "$CRON" <<'CRONTAB'
# Renouvellement Let's Encrypt de five.ifrit.fr — posé par deploy/install-five.sh.
# `renew` ne fait rien tant que le certificat a plus de 30 jours ; le hook ne
# recharge nginx que si un certificat a été remplacé.
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
17 4,16 * * * root certbot renew --quiet --deploy-hook "systemctl reload nginx"
CRONTAB
chmod 644 "$CRON"

# --- 6. Refermer le conteneur, maintenant que le HTTPS répond ------------------

dire "vérification de https://${DOMAINE}"
curl -fsS "https://${DOMAINE}/api/public/health" >/dev/null \
    || erreur "https://${DOMAINE} ne répond pas — voir  journalctl -u nginx  et  docker compose logs webapp"

poser_env() {
    if grep -q "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        echo "$1=$2" >> .env
    fi
}

dire "fermeture du conteneur sur la boucle locale"
poser_env WEBAPP_BIND 127.0.0.1
poser_env WEBAPP_COOKIE_SECURE true
# `up -d` recrée le conteneur : la publication du port fait partie de sa
# définition, un simple restart ne la changerait pas.
docker compose up -d webapp

printf 'attente du retour du service'
for _ in $(seq 1 30); do
    curl -fsS "https://${DOMAINE}/api/public/health" >/dev/null 2>&1 && break
    printf '.'; sleep 1
done; echo

# --- Le bilan ------------------------------------------------------------------

dire "bilan"
printf '  site      : ' ; curl -so /dev/null -w '%{http_code}\n' "https://${DOMAINE}/"
printf '  API       : ' ; curl -fsS "https://${DOMAINE}/api/public/health"; echo
printf '  redirection http : ' ; curl -so /dev/null -w '%{http_code}\n' "http://${DOMAINE}/"
printf '  certificat : expire ' ; openssl s_client -connect "${DOMAINE}:443" -servername "$DOMAINE" </dev/null 2>/dev/null \
    | openssl x509 -noout -enddate | cut -d= -f2
echo
echo "Terminé. Le port 8183 n'est plus joignable que depuis la machine ;"
echo "le renouvellement du certificat est dans ${CRON}."
