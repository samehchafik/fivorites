#!/usr/bin/env bash
# La passe quotidienne : rattraper les nouveautés et les modifications TMDB,
# puis les enrichir. Conçue pour une entrée de crontab sur l'hôte — voir
# doc/exploitation.md §7. Un lendemain ordinaire dure quelques minutes :
# `fetch_state` fait que chaque étape ne traite que ce qui a bougé.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p var/log
exec >>"var/log/nightly-$(date +%F).log" 2>&1
echo "=== nightly $(date -Is) ==="

# Le verrou : si la passe d'hier tourne encore (premier lancement, rattrapage),
# on ne double pas — c'est l'équivalent cron du conteneur nommé.
exec 9>var/nightly.lock
if ! flock -n 9; then
  echo "passe précédente encore en cours — on ne double pas"
  exit 0
fi

run() { docker compose run --rm sourcing "$@"; }

run tmdb export            # l'inventaire du jour : nouveautés et disparitions
run tmdb changes --days 2  # les modifiées (fenêtre de 2 j : tolère un cron raté)
run tmdb backfill          # collecte les nouvelles + recollecte les modifiées
run tmdb dates             # les dates des fraîchement collectées
run enrich --order recent  # leur enrichissement (les autres sont déjà vues)
# L'actualité dérivée des recollectes du jour : gratuit, incrémental (curseur),
# et APRÈS backfill — c'est lui qui fait grossir le brut, donc c'est sa fin qui
# rend les diffs disponibles. `|| true` : rien en aval ne fait échouer la passe.
run actualite-derive || true
docker compose run --rm admin catalog refresh   # la grille de l'admin
# L'index de recherche rattrape ce que la passe vient d'importer — APRÈS le
# refresh : la synchronisation relit les métadonnées dans la projection.
# `|| true` : ES absent ou jamais réindexé ne doit pas faire échouer la passe,
# l'admin retombe sur le SQL et la réponse d'API le dit (searchEngine).
docker compose run --rm admin search sync || true
# Le graphe rattrape la même passe : œuvres neuves, fiches recollectées, et —
# ce que l'index de recherche n'a pas — les œuvres notées depuis la veille, qui
# n'ont bougé ni dans le brut ni dans `fetch_state`.
# `|| true` pour la même raison : un Neo4j absent ou jamais projeté ne doit pas
# faire échouer la collecte, dont rien ne dépend de lui.
docker compose run --rm admin graphe sync || true

echo "=== fin $(date -Is) ==="
