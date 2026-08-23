"""Le client Neo4j du site public — le transport seul.

C'est la partie « transport » de `fiv_admin.graphe`, reprise telle quelle : la
Query API v2 en httpx, sans le pilote officiel. Ce module ne projette rien —
la projection appartient à l'admin (`fiv-admin graphe projeter`) ; ici on ne
fait que LIRE le graphe qu'elle entretient. Le vocabulaire (`FivOeuvre`,
`FIV_CITE`, les index vectoriels) vit dans `suggestions.py`, seul lecteur.
"""

from __future__ import annotations

import re
from typing import Any

import httpx


class GrapheErreur(RuntimeError):
    """Neo4j a refusé une instruction. Le message porte le code Neo4j, la
    seule chose exploitable pour trier une erreur de schéma d'une erreur de
    données."""


# La Query API refuse les retours à la ligne littéraux dans un `statement` :
# c'est du JSON, et le Cypher doit tenir sur une ligne. Cypher lit un saut de
# ligne comme une espace — sauf pour les commentaires `//`, qui avaleraient le
# reste une fois tout mis bout à bout. On les retire avant de plier.
_COMMENTAIRE = re.compile(r"^\s*//.*$", re.MULTILINE)


def une_ligne(cypher: str) -> str:
    """Une instruction Cypher, pliée sur une ligne pour la Query API."""
    return " ".join(_COMMENTAIRE.sub("", cypher).split())


class Graphe:
    """Un client Neo4j minimal, par la Query API v2.

    Sans transaction explicite : chaque requête est enveloppée par le serveur
    dans la sienne, et le site ne fait que des lectures.
    """

    def __init__(
        self,
        url: str,
        utilisateur: str,
        mot_de_passe: str,
        *,
        base: str = "neo4j",
        timeout: float = 10.0,
    ) -> None:
        self._chemin = f"/db/{base}/query/v2"
        self._http = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            auth=(utilisateur, mot_de_passe),
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers={"Accept": "application/json"},
        )

    async def fermer(self) -> None:
        await self._http.aclose()

    async def executer(self, cypher: str, **parametres: Any) -> list[dict[str, Any]]:
        """Une instruction, ses paramètres, ses lignes de résultat.

        Les paramètres passent par `parameters` et jamais par interpolation :
        Neo4j met en cache le plan d'exécution par forme de requête.
        """
        reponse = await self._http.post(
            self._chemin,
            json={"statement": une_ligne(cypher), "parameters": parametres},
        )
        if reponse.status_code == 401:
            raise GrapheErreur(
                "Neo4j refuse l'authentification — vérifier NEO4J_USER / NEO4J_PASSWORD"
            )
        corps = reponse.json()
        erreurs = corps.get("errors")
        if erreurs:
            premiere = erreurs[0]
            raise GrapheErreur(f"{premiere.get('code')} : {premiere.get('message')}")
        reponse.raise_for_status()
        donnees = corps.get("data") or {}
        champs: list[str] = donnees.get("fields") or []
        return [dict(zip(champs, ligne, strict=False)) for ligne in donnees.get("values") or []]
