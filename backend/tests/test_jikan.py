"""Client Jikan, sans réseau : transport simulé, horloge et attente simulées."""

import httpx
import pytest

from app.clients.jikan import JikanClient, JikanUnavailable, is_adult
from app.core.config import JikanSettings
from tests.conftest import FakeJikan

SETTINGS = JikanSettings(base_url="https://jikan.test/v4", timeout_s=1, max_retries=2,
                         cache_seconds=3600, failure_backoff_s=120)  # fmt: skip


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _client(fake, clock=None, sleeps=None):
    return JikanClient(SETTINGS, transport=httpx.MockTransport(fake),
                       sleep=(sleeps.append if sleeps is not None else lambda s: None),
                       clock=clock or Clock())  # fmt: skip


def test_adult_titles_are_filtered():
    items, _, stale = _client(FakeJikan()).season_now()
    assert {i["mal_id"] for i in items} == {1, 999} and stale is False
    assert is_adult({"rating": "Rx - Hentai"}) and is_adult({"genres": [{"name": "Hentai"}]})


def test_retries_on_429_then_succeeds():
    fake, sleeps = FakeJikan(statuses=[429, 503]), []
    items, _, _ = _client(fake, sleeps=sleeps).season_now()
    assert fake.calls == 3 and len(items) == 2
    assert sleeps[:2] == [1.0, 2.0]  # attente croissante


def test_gives_up_after_max_retries():
    fake = FakeJikan(statuses=[500, 500, 500])
    with pytest.raises(JikanUnavailable):
        _client(fake).season_now()
    assert fake.calls == 3  # 1 essai + 2 retries


def test_client_error_is_not_retried():
    fake = FakeJikan(statuses=[404])
    with pytest.raises(JikanUnavailable, match="404"):
        _client(fake).season_now()
    assert fake.calls == 1


def test_cache_avoids_second_call_then_expires():
    fake, clock = FakeJikan(), Clock()
    client = _client(fake, clock=clock)
    client.season_now()
    clock.now = 3599
    client.season_now()
    assert fake.calls == 1
    clock.now = 3601
    client.season_now()
    assert fake.calls == 2


def test_stale_cache_served_when_jikan_down_then_backoff():
    fake, clock = FakeJikan(), Clock()
    client = _client(fake, clock=clock)
    first, fetched, _ = client.season_now()
    fake.statuses = [503, 503, 503]
    clock.now = 4000
    items, fetched_again, stale = client.season_now()
    assert stale is True and items == first and fetched_again == fetched
    calls = fake.calls
    # Pendant le délai après échec : pas de nouvel essai, réponse périmée servie tout de suite.
    clock.now = 4000 + 119
    assert client.season_now()[2] is True and fake.calls == calls
    clock.now = 4000 + 121
    assert client.season_now()[2] is False and fake.calls == calls + 1


def test_failure_without_cache_is_not_retried_during_backoff():
    fake, clock = FakeJikan(statuses=[503] * 3), Clock()
    client = _client(fake, clock=clock)
    with pytest.raises(JikanUnavailable):
        client.season_now()
    with pytest.raises(JikanUnavailable, match="plus tard"):
        client.season_now()
    assert fake.calls == 3  # le 2e appel n'a pas relancé les retries


def test_concurrent_refresh_serves_stale_without_waiting():
    fake, clock = FakeJikan(), Clock()
    client = _client(fake, clock=clock)
    client.season_now()
    clock.now = 4000  # cache expiré
    client._lock.acquire()  # un autre thread est en train de rafraîchir
    try:
        items, _, stale = client.season_now()
    finally:
        client._lock.release()
    assert stale is True and len(items) == 2 and fake.calls == 1


@pytest.mark.parametrize("body", [b"<html>Cloudflare</html>", b"[1, 2]"])
def test_non_json_or_unexpected_body_is_a_failure(body):
    responses = [httpx.Response(200, content=body)] * 3

    def transport(request):
        return responses.pop()

    with pytest.raises(JikanUnavailable):
        _client(transport).season_now()


def test_retry_after_not_waited_on_last_attempt():
    sleeps = []
    fake = FakeJikan()

    def transport(request):
        fake.calls += 1
        return httpx.Response(429, headers={"Retry-After": "7"})

    with pytest.raises(JikanUnavailable):
        _client(transport, sleeps=sleeps).season_now()
    assert sleeps == [7.0, 7.0]  # 3 essais : on attend entre eux, pas après le dernier
