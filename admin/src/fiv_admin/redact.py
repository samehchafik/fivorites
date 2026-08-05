"""Masquage des secrets destinés à être affichés ou journalisés.

Jumeau de `fiv_sourcing.redact`, et volontairement identique : deux masquages
qui divergent, c'est celui qu'on a oublié de corriger qui fuite. Le doublon est
la contrepartie assumée de deux modules déployés séparément (voir `db.py`).

Deux fuites possibles, traitées ici :

- le mot de passe d'une URL de connexion, quand on trace la cible d'une
  commande — le cas courant de ce module ;
- un secret qui voyagerait en paramètre de requête. L'administration n'en met
  aucun dans ses URL (la session est un cookie `HttpOnly`), mais le filtre est
  posé quand même : il coûte un `re.sub` par ligne de journal, et un filet de
  sécurité qui suppose qu'on n'introduira jamais de paramètre sensible n'en est
  pas un.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit, urlunsplit

# `api_key` pour TMDB, les autres par précaution : ce filtre traverse tous les
# logs, autant qu'il couvre les noms usuels.
_SECRET_PARAM = re.compile(
    r"(?i)\b(api_key|apikey|access_token|session_id|password|passwd|secret|token)"
    r"=([^&\s\"'<>]+)"
)

# Un mot de passe est choisi par un humain : souvent court, souvent structuré.
# En montrer treize caractères en révélerait l'essentiel. Une clé d'API est
# tirée au hasard sur trente caractères ou plus — une empreinte n'y donne aucune
# prise. D'où deux traitements distincts.
_TOUJOURS_MASQUE = frozenset({"password", "passwd", "secret"})

HEAD, TAIL = 5, 8
_LONGUEUR_MINIMALE = HEAD + TAIL + 8


def fingerprint(value: str) -> str:
    """Empreinte lisible d'un secret : `b2788.....23721262`.

    Assez pour reconnaître la clé en usage — vérifier qu'une rotation a bien
    pris, distinguer deux environnements — pas assez pour s'en servir : sur une
    clé TMDB de 32 caractères hexadécimaux, il en reste 19 inconnus.

    En dessous d'une certaine longueur, on masque tout : sur un secret court,
    une empreinte en révélerait la majeure partie.
    """
    if len(value) < _LONGUEUR_MINIMALE:
        return "***"
    return f"{value[:HEAD]}.....{value[-TAIL:]}"


def redact_secrets(text: str) -> str:
    """Remplace la valeur des paramètres sensibles par leur empreinte."""

    def remplacer(match: re.Match[str]) -> str:
        nom, valeur = match.group(1), match.group(2)
        if nom.lower() in _TOUJOURS_MASQUE:
            return f"{nom}=***"
        return f"{nom}={fingerprint(valeur)}"

    return _SECRET_PARAM.sub(remplacer, text)


def redact_dsn(dsn: str) -> str:
    """Remplace le mot de passe d'une URL de connexion, garde le reste lisible.

    Sert à tracer la cible d'une commande sans écrire le secret — en conteneur,
    savoir sur quel hôte et quelle base on tape est presque toujours
    l'information qui manque.
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


class SecretFilter(logging.Filter):
    """Masque les secrets dans tout ce qui passe par le journal.

    Posé sur le gestionnaire plutôt que sur un logger particulier : la fuite
    vient d'une bibliothèque tierce, et on ne veut pas dépendre de la liste des
    bibliothèques qui journalisent des URL.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_secrets(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True
