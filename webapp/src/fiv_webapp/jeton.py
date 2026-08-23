"""Le jeton de session anonyme : un identifiant signé dans un cookie.

Même choix que `fiv_admin.security`, et pour les mêmes raisons : un
HMAC-SHA256 sur un JSON compact fait le travail d'un JWT sans importer une
bibliothèque, sans champ `alg` à valider et sans le piège `alg: none`. Le
cookie est `HttpOnly` — jamais lisible en JavaScript.

La différence avec l'admin : ici le sujet n'est pas un compte mais une session
anonyme — un UUID de `visiteur.session`, et rien d'autre. Le jeton ne porte
aucune donnée personnelle parce que le système n'en connaît aucune.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionAnonyme:
    session_id: str
    emise_le: int
    expire_le: int


class JetonSession:
    """Émet et lit les jetons, avec le secret et la durée de vie du service.

    Une classe plutôt que deux fonctions à trois paramètres : le secret et le
    TTL sont l'état du service, pas des arguments que chaque route devrait
    faire suivre.
    """

    def __init__(self, secret: str, *, ttl_seconds: int) -> None:
        self._secret = secret
        self._ttl = ttl_seconds

    def emettre(self, session_id: str, *, now: int | None = None) -> str:
        now = int(time.time()) if now is None else now
        corps = json.dumps(
            {"sid": session_id, "iat": now, "exp": now + self._ttl},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"{_b64(corps)}.{_b64(self._signer(corps))}"

    def lire(self, jeton: str, *, now: int | None = None) -> SessionAnonyme | None:
        """La session si le jeton est authentique et non expiré, sinon None.

        La signature est vérifiée **avant** de regarder le contenu : on ne lit
        pas un JSON dont on n'a pas encore prouvé l'origine.
        """
        now = int(time.time()) if now is None else now
        try:
            corps_b64, signature_b64 = jeton.split(".")
            corps = _unb64(corps_b64)
            signature = _unb64(signature_b64)
        except (ValueError, TypeError):
            return None

        if not hmac.compare_digest(signature, self._signer(corps)):
            return None

        try:
            charge = json.loads(corps)
            session_id = charge["sid"]
            emise_le = int(charge["iat"])
            expire_le = int(charge["exp"])
        except (ValueError, KeyError, TypeError):
            return None

        if not isinstance(session_id, str) or expire_le <= now:
            return None
        return SessionAnonyme(session_id=session_id, emise_le=emise_le, expire_le=expire_le)

    def _signer(self, corps: bytes) -> bytes:
        return hmac.new(self._secret.encode("utf-8"), corps, hashlib.sha256).digest()


def _b64(brut: bytes) -> str:
    return base64.urlsafe_b64encode(brut).decode("ascii").rstrip("=")


def _unb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))
