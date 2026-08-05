"""Affichage d'une URL de connexion sans son mot de passe."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_dsn(dsn: str) -> str:
    """Remplace le mot de passe par `***`, garde tout le reste lisible.

    Sert à tracer la cible d'une commande sans écrire le secret dans les logs —
    en conteneur, savoir sur quel hôte et quelle base on tape est presque
    toujours l'information qui manque.
    """
    parts = urlsplit(dsn)
    if not parts.hostname:
        return dsn

    auth = ""
    if parts.username:
        auth = parts.username
        if parts.password:
            auth += ":***"
        auth += "@"

    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"

    return urlunsplit((parts.scheme, f"{auth}{host}", parts.path, "", ""))
