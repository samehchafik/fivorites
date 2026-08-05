"""Client HTTP : limiteur de débit, reprise sur erreur, respect du Retry-After.

Volontairement écrit à la main plutôt qu'avec une bibliothèque de retry : le cas
qui compte ici est le 429 avec en-tête `Retry-After`, où le serveur nous dit
combien de temps attendre. Une politique de backoff générique ignorerait cette
information.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class RateLimiter:
    """Limiteur simple : au plus `rate` acquisitions par seconde, tous appelants
    confondus. Les créneaux sont réservés à l'avance, ce qui répartit les
    requêtes au lieu de les envoyer en rafales."""

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
            delay = slot - now
        if delay > 0:
            await asyncio.sleep(delay)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Ce qu'on a obtenu, y compris quand ça a échoué.

    Un 404 est un résultat, pas une erreur : TMDB supprime des séries, et savoir
    qu'un id a disparu est une information qu'on veut conserver.
    """

    url: str
    status: int
    payload: dict[str, Any] | None
    attempts: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HttpFetcher:
    """Enveloppe httpx : un seul point de sortie réseau pour tout le pipeline."""

    def __init__(
        self,
        *,
        rate_limit: float,
        timeout: float = 30.0,
        max_attempts: int = 5,
        user_agent: str = "fivorites-sourcing/0.1",
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._limiter = RateLimiter(rate_limit)
        self._max_attempts = max(1, max_attempts)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json", **(headers or {})},
            follow_redirects=True,
        )

    async def __aenter__(self) -> HttpFetcher:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> FetchResult:
        last_error: str | None = None
        status = 0

        for attempt in range(1, self._max_attempts + 1):
            await self._limiter.acquire()
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                status = 0
            else:
                status = response.status_code
                if response.is_success:
                    try:
                        return FetchResult(url, status, response.json(), attempt)
                    except ValueError as exc:
                        last_error = f"réponse non-JSON: {exc}"
                elif status not in RETRYABLE_STATUS:
                    # 404, 401, 403… : définitif. On le remonte tel quel pour
                    # qu'il soit tracé dans fetch_state.
                    return FetchResult(url, status, None, attempt, response.text[:500])
                else:
                    last_error = f"HTTP {status}"
                    retry_after = _parse_retry_after(response)
                    if retry_after is not None and attempt < self._max_attempts:
                        log.warning("HTTP %s sur %s, attente %.1fs", status, url, retry_after)
                        await asyncio.sleep(retry_after)
                        continue

            if attempt < self._max_attempts:
                delay = _backoff(attempt)
                log.warning("échec %s sur %s, reprise dans %.1fs", last_error, url, delay)
                await asyncio.sleep(delay)

        return FetchResult(url, status, None, self._max_attempts, last_error)


def _backoff(attempt: int) -> float:
    """Exponentiel plafonné, avec bruit pour éviter que N tâches reprennent
    toutes exactement en même temps."""
    return min(2.0**attempt, 30.0) * (0.5 + random.random() / 2)


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        # La forme « date HTTP » est autorisée par la RFC mais TMDB ne l'utilise
        # pas ; on retombe sur le backoff plutôt que de parser une date.
        return None
