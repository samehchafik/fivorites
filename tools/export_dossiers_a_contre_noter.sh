#!/usr/bin/env bash
#
# Exporte les dossiers des œuvres qui attendent une contre-note, pour les
# faire juger hors de l'API — par un modèle Claude à qui l'on colle le
# résultat, faute de clé Anthropic.
#
# Ce qu'il produit : un JSON ne contenant QUE l'identifiant et le texte
# anglais du dossier. Surtout pas les notes d'OpenAI — un contre-juge qui
# les voit n'en est plus un, il est tiré vers elles sans le vouloir.
#
#   ./export_dossiers_a_contre_noter.sh 1399 549 60625 > dossiers.json
#   ./export_dossiers_a_contre_noter.sh --pending v2 > dossiers.json
#
# `--pending <version>` demande à Postgres la liste des essais de ce barème
# qui portent un verdict OpenAI et pas encore de contre-note. Il lui faut
# psql et DATABASE_URL ; sinon, passer les identifiants à la main.
#
# Le mot de passe est demandé au clavier, jamais en argument : une ligne de
# commande finit dans l'historique du shell.

set -euo pipefail

BASE="${ADMIN_URL:-http://ifrit.fr:8182}"
COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT

if [[ $# -eq 0 ]]; then
    echo "usage : $0 <id_tmdb...> | --pending <version_bareme>" >&2
    exit 2
fi

if [[ "$1" == "--pending" ]]; then
    version="${2:?--pending attend une version de barème, par exemple v2}"
    mapfile -t IDS < <(psql "${DATABASE_URL:?DATABASE_URL doit être défini}" -tAc "
        select distinct on (id_tmdb) id_tmdb
        from notation.training_run
        where rubric_version = '${version}' and openai is not null and claude is null
        order by id_tmdb, created_at desc
    ")
else
    IDS=("$@")
fi

if [[ ${#IDS[@]} -eq 0 ]]; then
    echo "aucune œuvre en attente de contre-note." >&2
    exit 0
fi

read -rp "Identifiant admin : " USERNAME
read -rsp "Mot de passe : " PASSWORD
echo >&2

# `--data-binary @-` : le mot de passe passe par l'entrée standard, il
# n'apparaît donc ni dans la liste des processus ni dans l'historique.
python3 -c '
import json, sys
print(json.dumps({"username": sys.argv[1], "password": sys.argv[2]}))
' "$USERNAME" "$PASSWORD" |
    curl -sS -c "$COOKIES" -X POST "$BASE/api/auth/login" \
        -H 'Content-Type: application/json' --data-binary @- >/dev/null

echo "connecté — ${#IDS[@]} dossier(s) à récupérer" >&2

{
    printf '{\n  "dossiers": [\n'
    premier=1
    for id in "${IDS[@]}"; do
        [[ -z "$id" ]] && continue
        reponse="$(curl -sS -b "$COOKIES" "$BASE/api/training/works/$id/dossier")"
        # On ne garde que l'identifiant, le titre et le texte : tout le reste
        # (empreintes, compteurs de sections) est du bruit pour un juge.
        ligne="$(printf '%s' "$reponse" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(json.dumps({"idTmdb": d["idTmdb"], "title": d["title"], "text": d["text"]},
                 ensure_ascii=False, indent=4))
')"
        [[ $premier -eq 0 ]] && printf ',\n'
        printf '%s' "$ligne"
        premier=0
        echo "  $id ✓" >&2
    done
    printf '\n  ]\n}\n'
}
