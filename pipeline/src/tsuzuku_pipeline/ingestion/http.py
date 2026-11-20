"""Client HTTP poli pour les API publiques (Jikan, AniList) : débit limité, retries, backoff.

- Débit : au moins `min_interval_s` entre deux appels (Jikan : 1 req/s ; AniList : sous 30/min).
- Retries sur erreur réseau, 429 et 5xx, avec attente croissante (2^n s, plafonnée) ; l'en-tête
  Retry-After, s'il est fourni, prime.
- AniList annonce son quota restant (X-RateLimit-Remaining) et l'heure de remise à zéro
  (X-RateLimit-Reset) : à 0, on attend la remise à zéro AVANT d'appeler, plutôt que de
  provoquer un 429.
- Aucune information identifiante n'est envoyée (User-Agent par défaut de httpx).
Les fonctions d'attente et d'horloge sont injectables : les tests ne dorment pas.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger("tsuzuku_pipeline.ingestion")

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_WAIT_S = 60.0


class HttpError(Exception):
    """Appel impossible après les retries, ou réponse non exploitable."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PoliteClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        min_interval_s: float,
        max_retries: int,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)
        self._min_interval, self._max_retries = min_interval_s, max_retries
        self._sleep, self._clock, self._wall = sleep, clock, wall_clock
        self._last_call: float | None = None
        self._quota_reset_at: float | None = None  # heure murale (epoch) de remise à zéro
        self.calls = 0  # pour les rapports d'exécution

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _wait_turn(self) -> None:
        if self._quota_reset_at is not None:
            wait = self._quota_reset_at - self._wall()
            if wait > 0:
                logger.info("Quota épuisé : attente de %.0f s (remise à zéro annoncée)", wait)
                self._sleep(min(wait, MAX_WAIT_S))
            self._quota_reset_at = None
        if self._last_call is not None:
            wait = self._min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _note_quota(self, resp: httpx.Response) -> None:
        remaining, reset = (
            resp.headers.get("X-RateLimit-Remaining"),
            resp.headers.get("X-RateLimit-Reset"),
        )
        if remaining == "0" and reset and reset.isdigit():
            self._quota_reset_at = float(reset)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            last = attempt + 1 == attempts
            self._wait_turn()
            self.calls += 1
            try:
                resp = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                logger.warning("%s %s : %s (essai %d/%d)", method, path, type(exc).__name__,
                               attempt + 1, attempts)  # fmt: skip
                status = None
            else:
                self._note_quota(resp)
                if resp.is_success:
                    return resp
                status = resp.status_code
                if status not in RETRY_STATUSES:
                    raise HttpError(f"{method} {path} : HTTP {status}", status)
                logger.warning("%s %s : HTTP %d (essai %d/%d)", method, path, status,
                               attempt + 1, attempts)  # fmt: skip
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit() and not last:
                    self._sleep(min(float(retry_after), MAX_WAIT_S))
                    continue
            if not last:
                self._sleep(min(2.0**attempt, MAX_WAIT_S))
        raise HttpError(f"{method} {path} : échec après {attempts} essais", status)

    def get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return _json(self.request("GET", path, **kwargs), path)

    def post_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return _json(self.request("POST", path, **kwargs), path)


def _json(resp: httpx.Response, path: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        raise HttpError(f"{path} : réponse qui n'est pas du JSON", resp.status_code) from None
    if not isinstance(body, dict):
        raise HttpError(f"{path} : JSON inattendu ({type(body).__name__})", resp.status_code)
    return body
