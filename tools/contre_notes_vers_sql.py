#!/usr/bin/env python3
"""Des contre-notes en JSON vers le SQL qui les enregistre.

Le contre-jugement se fait hors API — un modèle Claude lit les dossiers dans
une conversation et rend ses notes. Ce script fait le reste, et il le fait
seul : **le jugement vient du modèle, la mécanique vient d'ici**. Un contre-
juge n'a pas à écrire du SQL, et surtout pas à recopier des empreintes à la
main — c'est là que se glissent les erreurs de provenance qu'on ne détecte
jamais après coup.

    ./contre_notes_vers_sql.py dossiers.json notes.json > contre_notes.sql
    psql "$DATABASE_URL" -f contre_notes.sql

`dossiers.json` est la sortie d'`export_dossiers_a_contre_noter.sh` : c'est
lui qui porte le texte, donc l'empreinte du dossier — recalculée ici plutôt
que transportée, pour qu'elle corresponde forcément à ce qui a été lu.

`notes.json` est ce que le contre-juge produit :

    {
      "modele": "claude-haiku-4-5-console",
      "rubricVersion": "v2",
      "notes": [
        {"idTmdb": 1399, "scores": {"luminosite": 3, "intensite": 7,
                                    "humour": 3, "exigence": 6,
                                    "etrangete": 5, "sensoriel": null}}
      ]
    }

`null` est une réponse valide et attendue : la consigne autorise le « je ne
sais pas », et une note inventée vaut moins qu'une note absente.

Le nom du modèle doit commencer par `claude` — ce n'est pas cosmétique :
l'entraînement des poids exclut `modele like 'claude%%'`, et c'est ce préfixe
qui garantit qu'un contre-juge ne servira jamais à entraîner la régression
qu'il est censé contredire.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

AXES = ("luminosite", "intensite", "humour", "exigence", "etrangete", "sensoriel")


def quote(text: str) -> str:
    """Une chaîne littérale SQL — les apostrophes doublées, rien d'autre."""
    return "'" + text.replace("'", "''") + "'"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    dossiers = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["dossiers"]
    notes = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    modele = notes["modele"]
    if not modele.startswith("claude"):
        print(
            f"le modèle « {modele} » ne commence pas par « claude » : "
            "l'entraînement des poids ne l'exclurait pas, et un contre-juge "
            "entraînerait la régression qu'il doit contredire.",
            file=sys.stderr,
        )
        return 1

    version = notes["rubricVersion"]
    # L'empreinte du dossier tel qu'il a été lu, recalculée depuis le texte —
    # même formule que `build_dossier`.
    empreintes = {
        d["idTmdb"]: hashlib.sha256(d["text"].encode("utf-8")).hexdigest() for d in dossiers
    }

    lignes: list[str] = [
        "-- Contre-notes enregistrées hors API.",
        f"-- Barème {version} · modèle {modele} · {len(notes['notes'])} œuvre(s).",
        "--",
        "-- L'empreinte du prompt est résolue par la requête elle-même : la",
        "-- recopier serait la première occasion de se tromper de barème.",
        "begin;",
        "",
    ]

    for note in notes["notes"]:
        id_tmdb = note["idTmdb"]
        if id_tmdb not in empreintes:
            print(f"œuvre {id_tmdb} absente de l'export des dossiers", file=sys.stderr)
            return 1
        sha = empreintes[id_tmdb]
        scores = note["scores"]

        inconnus = set(scores) - set(AXES)
        if inconnus:
            print(f"œuvre {id_tmdb} : axes inconnus {sorted(inconnus)}", file=sys.stderr)
            return 1

        lignes.append(f"-- œuvre {id_tmdb}")
        for axe in AXES:
            valeur = scores.get(axe)
            if valeur is not None and not (1 <= valeur <= 10):
                print(f"œuvre {id_tmdb}, {axe} : {valeur} hors de l'échelle 1-10", file=sys.stderr)
                return 1
            valeur_sql = "null" if valeur is None else str(int(valeur))
            lignes.append(
                "insert into notation.score (id_tmdb, axe, valeur, confiance,"
                " rubric_version, modele, input_sha256, prompt_sha256)\n"
                f"select {id_tmdb}, {quote(axe)}, {valeur_sql}, null,"
                f" {quote(version)}, {quote(modele)}, {quote(sha)},\n"
                "       encode(sha256(prompt::bytea), 'hex')\n"
                f"from notation.rubric where version = {quote(version)};"
            )

        # Le journal : la contre-note rejoint l'essai le plus récent de cette
        # œuvre sur ce barème — exactement ce que fait le bouton du front.
        verdict = json.dumps(
            {
                "model": modele,
                "scores": {
                    axe: {"score": scores.get(axe), "confidence": None} for axe in AXES
                },
            },
            ensure_ascii=False,
        )
        lignes.append(
            "update notation.training_run set claude = "
            f"{quote(verdict)}::jsonb, claude_at = now()\n"
            "where id = (select id from notation.training_run\n"
            f"            where id_tmdb = {id_tmdb} and rubric_version = {quote(version)}\n"
            "            order by created_at desc limit 1);"
        )
        lignes.append("")

    lignes.append("commit;")
    print("\n".join(lignes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
