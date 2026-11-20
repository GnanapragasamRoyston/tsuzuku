"""Briques de sécurité, sans base : hachage, jetons, limitation de débit."""

import pytest

from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import (
    InvalidToken,
    PasswordHasher,
    create_token,
    decode_token,
)

SECRET = "s" * 64


@pytest.fixture(scope="module")
def hasher():
    return PasswordHasher()


def test_hash_and_verify(hasher):
    h = hasher.hash("correct horse battery")
    assert h.startswith("$argon2id$")
    assert hasher.verify(h, "correct horse battery")
    assert not hasher.verify(h, "Correct horse battery")


def test_hashes_are_salted(hasher):
    assert hasher.hash("même mot de passe") != hasher.hash("même mot de passe")


def test_verify_without_account_takes_the_same_path(hasher):
    # Email inconnu : on vérifie quand même contre un hash factice (même durée de réponse).
    assert hasher.verify(None, "n'importe quoi") is False


def test_verify_rejects_a_corrupted_hash(hasher):
    assert hasher.verify("pas-un-hash", "x") is False


def test_token_roundtrip():
    token = create_token(user_id=42, token_version=3, secret=SECRET, ttl_hours=1)
    assert decode_token(token, SECRET) == (42, 3)


@pytest.mark.parametrize("token", ["", "a.b.c", create_token(1, 0, "autre" * 13, 1)])
def test_decode_rejects_bad_tokens(token):
    with pytest.raises(InvalidToken):
        decode_token(token, SECRET)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_blocks_after_max_attempts_then_recovers():
    clock = Clock()
    limiter = SlidingWindowLimiter(max_attempts=3, window_s=60, clock=clock)
    for _ in range(3):
        assert limiter.retry_after("ip:1") == 0
        limiter.hit("ip:1")
    assert 0 < limiter.retry_after("ip:1") <= 60
    assert limiter.retry_after("ip:2") == 0  # clés indépendantes
    clock.now += 61
    assert limiter.retry_after("ip:1") == 0


def test_limiter_window_slides():
    clock = Clock()
    limiter = SlidingWindowLimiter(max_attempts=2, window_s=60, clock=clock)
    limiter.hit("k")
    clock.now += 30
    limiter.hit("k")
    clock.now += 31  # le 1er essai sort de la fenêtre, pas le 2e
    assert limiter.retry_after("k") == 0
    limiter.hit("k")
    assert limiter.retry_after("k") > 0


def test_limiter_reset_and_memory_is_bounded():
    clock = Clock()
    limiter = SlidingWindowLimiter(max_attempts=1, window_s=60, clock=clock)
    limiter.hit("email:a")
    limiter.reset("email:a")
    assert limiter.retry_after("email:a") == 0
    for i in range(1000):
        limiter.hit(f"ip:{i}")
    clock.now += 61
    limiter.hit("ip:new")  # les clés expirées sont purgées au passage
    assert len(limiter) == 1


def test_acquire_is_atomic_across_keys():
    limiter = SlidingWindowLimiter(max_attempts=2, window_s=60, clock=Clock())
    assert limiter.acquire("ip:1", "email:a") == 0
    assert limiter.acquire("ip:1", "email:b") == 0
    # ip:1 est à 2 : refusé, et RIEN n'est compté pour email:c.
    assert limiter.acquire("ip:1", "email:c") > 0
    assert limiter.retry_after("email:c") == 0


def test_acquire_under_concurrency_never_exceeds_the_limit():
    from concurrent.futures import ThreadPoolExecutor

    limiter = SlidingWindowLimiter(max_attempts=5, window_s=60)
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(lambda _: limiter.acquire("ip:1"), range(200)))
    assert results.count(0) == 5


def test_release_gives_back_the_last_attempt():
    limiter = SlidingWindowLimiter(max_attempts=1, window_s=60, clock=Clock())
    assert limiter.acquire("ip:1") == 0
    limiter.release("ip:1")  # connexion réussie : l'essai ne compte pas
    assert limiter.acquire("ip:1") == 0
