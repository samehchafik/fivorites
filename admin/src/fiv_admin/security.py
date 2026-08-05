"""Mots de passe et jetons de session.

Deux choix à expliquer.

**scrypt plutôt que bcrypt ou argon2** : il est dans la bibliothèque standard,
donc rien à installer, rien à faire suivre dans l'image, et pas de dépendance
native à recompiler. Il est à coût mémoire, ce qui est exactement la propriété
qu'on cherche face à une attaque par GPU. Pour une poignée de comptes
d'administration, c'est le bon compromis.

**Un cookie signé plutôt qu'un JWT** : le besoin tient en trois champs (qui,
depuis quand, jusqu'à quand). Un HMAC-SHA256 sur un JSON compact fait le même
travail sans importer une bibliothèque, sans champ `alg` à valider et sans le
piège `alg: none`. Le cookie est `HttpOnly` — le jeton n'est jamais lisible en
JavaScript, donc jamais exfiltrable par une injection dans le front.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

# 2^15 tours, 16 Mio × 4 de mémoire : environ 100 ms par vérification sur un
# poste récent. Assez lent pour rendre une attaque par dictionnaire coûteuse,
# assez rapide pour ne pas se voir à la connexion.
_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 1 << 26  # 64 Mio — explicite, sinon OpenSSL refuse au-delà de 32 Mio
_SALT_BYTES = 16
_KEY_BYTES = 32


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$sel$empreinte`, tout en base64 sans remplissage.

    Les paramètres sont dans la chaîne : le jour où on les durcit, les anciens
    mots de passe restent vérifiables sans migration.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _b64(salt),
            _b64(derived),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    """Comparaison à temps constant. Toute anomalie de format renvoie faux —
    un hachage illisible n'est pas une raison d'ouvrir la porte."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        derived = _scrypt(password, salt, int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_KEY_BYTES,
    )


@dataclass(frozen=True, slots=True)
class Session:
    username: str
    issued_at: int
    expires_at: int


def issue_session(username: str, secret: str, *, ttl_seconds: int, now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    body = json.dumps(
        {"sub": username, "iat": now, "exp": now + ttl_seconds},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{_b64(body)}.{_b64(_sign(body, secret))}"


def read_session(token: str, secret: str, *, now: int | None = None) -> Session | None:
    """Renvoie la session si le jeton est authentique et non expiré, sinon None.

    La signature est vérifiée **avant** de regarder le contenu : on ne lit pas
    un JSON dont on n'a pas encore prouvé l'origine.
    """
    now = int(time.time()) if now is None else now
    try:
        body_b64, sig_b64 = token.split(".")
        body = _unb64(body_b64)
        signature = _unb64(sig_b64)
    except (ValueError, TypeError):
        return None

    if not hmac.compare_digest(signature, _sign(body, secret)):
        return None

    try:
        payload = json.loads(body)
        username = payload["sub"]
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (ValueError, KeyError, TypeError):
        return None

    if not isinstance(username, str) or expires_at <= now:
        return None
    return Session(username=username, issued_at=issued_at, expires_at=expires_at)


def _sign(body: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LoginThrottle:
    """Freinage des tentatives, par couple (compte, adresse).

    En mémoire, donc remis à zéro au redémarrage et non partagé entre
    instances : ça n'arrête pas une attaque distribuée, ce n'est pas ce qu'on
    lui demande. Ça rend le forçage d'un mot de passe depuis une machine
    inopérant, et c'est ce qui manque le plus souvent à un formulaire de
    connexion.
    """

    def __init__(self, max_attempts: int, lockout_seconds: int) -> None:
        self._max = max_attempts
        self._lockout = lockout_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}

    def locked_for(self, username: str, address: str, *, now: float | None = None) -> int:
        """Secondes restantes avant de pouvoir réessayer. 0 si la voie est libre."""
        now = time.monotonic() if now is None else now
        recent = self._recent(username, address, now)
        if len(recent) < self._max:
            return 0
        return max(1, int(self._lockout - (now - recent[0])))

    def record_failure(self, username: str, address: str, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        key = (username, address)
        self._failures[key] = [*self._recent(username, address, now), now]

    def reset(self, username: str, address: str) -> None:
        self._failures.pop((username, address), None)

    def _recent(self, username: str, address: str, now: float) -> list[float]:
        window = self._failures.get((username, address), [])
        return [at for at in window if now - at < self._lockout]
