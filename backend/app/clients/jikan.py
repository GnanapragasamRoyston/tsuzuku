"""Client de l'API Jikan v4 (MyAnimeList, sans clé) : saison en cours.

Jikan limite à 3 requêtes/s et 60/min, et renvoie parfois 429 ou 5xx (SPEC § 12). D'où :
- timeout sur chaque appel ;
- retries avec attente croissante (1 s, 2 s, 4 s…, ou Retry-After si fourni, plafonné) ;
- cache en mémoire : la saison en cours change peu dans l'heure ;
- si Jikan tombe alors qu'une réponse est en cache, on sert la dernière connue (marquée stale)
  et on ne retente qu'après un délai (failure_backoff_s) ;
- un seul rafraîchissement à la fois, sans faire attendre les autres requêtes.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import JikanSettings

logger = logging.getLogger("tsuzuku_api.jikan")

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_PAGES = 4  # une saison compte ~70-100 animes, 25 par page
MAX_WAIT_S = 10.0


class JikanUnavailable(Exception):
    """Jikan n'a pas répondu correctement après les retries, et rien n'est en cache."""


def is_adult(item: dict[str, Any]) -> bool:
    # Même règle que le pipeline (ADR 002) : rating « Rx » ou genre Hentai. Jikan filtre déjà
    # avec sfw=true ; on revérifie (défense en profondeur).
    rating = item.get("rating") or ""
    genres = {g.get("name") for g in item.get("genres") or []}
    return rating.startswith("Rx") or "Hentai" in genres


@dataclass
class _Cached:
    items: list[dict[str, Any]]
    fetched_at: str
    # Instant (horloge monotone) à partir duquel on retente Jikan.
    refresh_after: float
    stale: bool


class JikanClient:
    def __init__(
        self,
        settings: JikanSettings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        # User-Agent par défaut de httpx : aucune information sur le projet n'est envoyée.
        self._http = httpx.Client(
            base_url=settings.base_url, timeout=settings.timeout_s, transport=transport
        )
        self._sleep, self._clock = sleep, clock
        # Un seul rafraîchissement à la fois. Les autres requêtes ne l'attendent PAS si une
        # réponse (même périmée) existe : sinon, Jikan en panne figerait les threads de l'API.
        self._lock = threading.Lock()
        self._cache: _Cached | None = None
        # Jikan en échec sans rien en cache : pas de nouvel essai avant cet instant.
        self._failed_until = 0.0

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        attempts = self._settings.max_retries + 1
        for attempt in range(attempts):
            last = attempt + 1 == attempts
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                logger.warning("Jikan %s : %s (essai %d/%d)", path, type(exc).__name__,
                               attempt + 1, attempts)  # fmt: skip
            else:
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except ValueError:
                        body = None  # ex. page HTML d'un proxy : traitée comme une panne
                    if isinstance(body, dict):
                        return body
                    logger.warning("Jikan %s : réponse illisible (essai %d/%d)", path,
                                   attempt + 1, attempts)  # fmt: skip
                elif resp.status_code not in RETRY_STATUSES:
                    raise JikanUnavailable(f"Jikan a répondu {resp.status_code}")
                else:
                    logger.warning("Jikan %s : HTTP %d (essai %d/%d)", path, resp.status_code,
                                   attempt + 1, attempts)  # fmt: skip
                    retry_after = resp.headers.get("Retry-After", "")
                    if retry_after.isdigit() and not last:
                        self._sleep(min(float(retry_after), MAX_WAIT_S))
                        continue
            if not last:
                self._sleep(min(2.0**attempt, MAX_WAIT_S))
        raise JikanUnavailable("Jikan indisponible après plusieurs essais")

    def _fetch_season(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = self._get("/seasons/now", {"sfw": "true", "page": page})
            items.extend(body.get("data") or [])
            if not (body.get("pagination") or {}).get("has_next_page"):
                break
            self._sleep(0.4)  # rester sous 3 requêtes/s
        # Une même œuvre peut apparaître sur deux pages si le classement bouge entre deux appels.
        unique = {i["mal_id"]: i for i in items if isinstance(i, dict) and "mal_id" in i}
        return [i for i in unique.values() if not is_adult(i)]

    def _serve(self, cached: _Cached, stale: bool) -> tuple[list[dict[str, Any]], str, bool]:
        return cached.items, cached.fetched_at, stale

    def season_now(self) -> tuple[list[dict[str, Any]], str, bool]:
        """(animes de la saison, date de récupération ISO, stale)."""
        cached = self._cache
        if cached and self._clock() < cached.refresh_after:
            return self._serve(cached, cached.stale)
        if cached is None and self._clock() < self._failed_until:
            raise JikanUnavailable("Jikan indisponible (nouvel essai plus tard)")
        if not self._lock.acquire(blocking=cached is None):
            # Un rafraîchissement est déjà en cours : on sert la dernière réponse sans attendre.
            return self._serve(cached, True)
        try:
            now = self._clock()
            cached = self._cache  # un autre thread a pu rafraîchir pendant qu'on attendait
            if cached and now < cached.refresh_after:
                return self._serve(cached, cached.stale)
            if cached is None and now < self._failed_until:
                raise JikanUnavailable("Jikan indisponible (nouvel essai plus tard)")
            try:
                items = self._fetch_season()
            except JikanUnavailable:
                backoff = now + self._settings.failure_backoff_s
                if cached is None:
                    self._failed_until = backoff
                    raise
                logger.warning("Jikan indisponible : dernière réponse connue servie")
                self._cache = _Cached(cached.items, cached.fetched_at, backoff, stale=True)
                return self._serve(self._cache, True)
            fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._cache = _Cached(items, fetched_at, now + self._settings.cache_seconds, False)
            return self._serve(self._cache, False)
        finally:
            self._lock.release()
