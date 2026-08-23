#!/usr/bin/env bash
# Noter TOUT le catalogue avec l'élève distillé, de bout en bout.
#
# Une commande, rien à retenir, rien à enchaîner à la main :
#
#     scripts/notation-eleve.sh
#
# Ce qu'elle fait, dans l'ordre : réentraîne la régression dans l'espace de
# l'élève, chiffre ce qui reste à faire, note tout le catalogue, puis pousse
# les empreintes fraîches dans le graphe.
#
# POURQUOI UN SCRIPT PLUTÔT QUE QUATRE COMMANDES. Parce que les quatre ne sont
# pas interchangeables et qu'en oublier une ne se voit pas :
#
#   * `EMBEDDER` doit être le MÊME partout. Une seule commande lancée sans lui
#     repart sur l'encodeur d'API — silencieusement, et en payant. Le script le
#     passe à chaque appel plutôt que de compter sur le `.env`.
#   * `training poids` DOIT précéder `notation generer`. Les poids vivent dans
#     l'espace de leur encodeur ; ceux d'un autre modèle rendraient six nombres
#     plausibles et faux. `generer` refuse, mais autant ne pas s'y frotter.
#   * le graphe ne se met pas à jour tout seul : sans la dernière étape, les
#     notes existent en base et la recommandation ne les voit pas.
#
# Relançable sans y penser : chaque étape saute ce qui est déjà fait, et une
# coupure ne coûte que le lot en cours. À détacher — comptez plusieurs heures
# sur le catalogue entier.
#
#     nohup scripts/notation-eleve.sh &>/dev/null &
#
# ⚠️ Les livres n'y sont pas : `notation generer` ne connaît que `series` et
# `movies`, et le dossier des livres reste à écrire. Leurs œuvres resteront
# sans note tant que ce lot n'est pas fait.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELE="${MODELE:-eleve-distille}"
# Le chemin est celui du CONTENEUR : le compose monte ./export sur /modeles.
# Surtout pas /opt/models, qui est le cache fastembed de l'image — monter
# par-dessus masque le modèle embarqué et rend le cache non inscriptible.
EMBEDDER="local:/modeles/${MODELE}"

SANS_POIDS=0
[[ "${1:-}" == "--sans-poids" ]] && SANS_POIDS=1

mkdir -p var/log
exec >>"var/log/notation-$(date +%F).log" 2>&1
echo "=== notation ($MODELE) $(date -Is) ==="

# Le verrou : deux passes concurrentes encoderaient les mêmes œuvres deux fois
# et se marcheraient dessus sur les mêmes lignes de `notation.score`.
exec 9>var/notation.lock
if ! flock -n 9; then
  echo "une passe de notation tourne déjà — on ne double pas"
  exit 0
fi

# Le modèle avant tout le reste : sans lui, la première commande partirait
# encoder pendant vingt minutes avant d'échouer, ou pire, retomberait sur un
# autre encodeur.
if [[ ! -f "export/${MODELE}/model.onnx" ]]; then
  echo "ERREUR : export/${MODELE}/model.onnx introuvable."
  echo "→ produire l'élève d'abord : voir distillation/README.md"
  exit 1
fi

run() { docker compose run --rm -e "EMBEDDER=$EMBEDDER" admin "$@"; }

# 1. Les poids, dans l'espace de l'élève. Sur l'historique complet des notes du
#    juge — elles ne bougent pas d'une passe à l'autre, d'où `--sans-poids`
#    quand on relance une notation interrompue le jour même.
if [[ $SANS_POIDS -eq 0 ]]; then
  echo "--- poids ($(date -Is))"
  run training poids
else
  echo "--- poids : sautés (--sans-poids)"
fi

# 2. L'état des lieux, pour le journal. Gratuit, n'écrit rien : c'est la trace
#    de ce qui restait à faire avant la passe, seule façon de relire plus tard
#    ce que celle-ci a réellement produit.
echo "--- devis ($(date -Is))"
run notation devis

# 3. La notation elle-même. C'est l'étape longue.
echo "--- génération ($(date -Is))"
run notation generer

# 4. Le graphe reprend les œuvres notées depuis son dernier passage. `|| true` :
#    un Neo4j absent ne doit pas faire échouer une notation qui, elle, est en
#    base — même règle que la passe nocturne.
echo "--- graphe ($(date -Is))"
docker compose run --rm admin graphe sync || true

echo "=== fin $(date -Is) ==="
