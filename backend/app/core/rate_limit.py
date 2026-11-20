"""Limitation de débit en mémoire (fenêtre glissante), pour la connexion, l'inscription et la
suppression de compte.

En mémoire du processus : simple et suffisant tant que l'API tourne en une seule instance.
Limite connue (ADR 008) : remis à zéro au redémarrage, et non partagé entre plusieurs instances
(Cloud Run, phase 11) ; il faudra alors un stockage commun (Postgres ou Redis).
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(self, max_attempts: int, window_s: int,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = clock()
        # Les routes `def` de FastAPI tournent dans un pool de threads : accès concurrents.
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._hits)

    def _trim(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _sweep(self, now: float) -> None:
        # Purge complète au plus une fois par fenêtre : la mémoire reste bornée par les clés
        # actives, sans parcourir toutes les clés à chaque requête.
        if now - self._last_sweep < self.window_s:
            return
        self._last_sweep = now
        for key in list(self._hits):
            self._trim(key, now)

    def _wait(self, key: str, now: float) -> int:
        hits = self._trim(key, now)
        if hits is None or len(hits) < self.max_attempts:
            return 0
        return max(1, math.ceil(hits[0] + self.window_s - now))

    def acquire(self, *keys: str) -> int:
        """Réserve un essai pour chaque clé, ATOMIQUEMENT : 0 si permis (essai compté), sinon
        les secondes à attendre (rien n'est compté).

        Vérifier puis compter sous le même verrou : sinon une rafale de requêtes simultanées
        passerait toute la vérification avant le premier comptage (revue de sécurité).
        """
        with self._lock:
            now = self._clock()
            self._sweep(now)
            wait = max(self._wait(k, now) for k in keys)
            if wait:
                return wait
            for k in keys:
                self._hits.setdefault(k, deque()).append(now)
            return 0

    def retry_after(self, key: str) -> int:
        """0 si un essai est permis ; sinon, secondes avant le prochain essai possible."""
        with self._lock:
            return self._wait(key, self._clock())

    def hit(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._sweep(now)
            self._hits.setdefault(key, deque()).append(now)

    def release(self, key: str) -> None:
        """Rend l'essai le plus récent (une connexion réussie ne compte pas comme un échec)."""
        with self._lock:
            hits = self._hits.get(key)
            if hits:
                hits.pop()
                if not hits:
                    del self._hits[key]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
