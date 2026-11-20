"""Client HTTP poli : sans réseau, horloge et attente simulées."""

import httpx
import pytest

from tsuzuku_pipeline.ingestion.http import HttpError, PoliteClient


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def sleep(self, s):
        self.slept.append(s)
        self.now += s

    def __call__(self):
        return self.now


def _client(handler, clock=None, min_interval=1.0, retries=2):
    clock = clock or Clock()
    return PoliteClient("https://api.test", timeout_s=1, min_interval_s=min_interval,
                        max_retries=retries, transport=httpx.MockTransport(handler),
                        sleep=clock.sleep, clock=clock, wall_clock=clock), clock  # fmt: skip


def test_calls_are_spaced_by_min_interval():
    client, clock = _client(lambda r: httpx.Response(200, json={"ok": True}))
    client.get_json("/a")
    client.get_json("/b")
    assert clock.slept == [1.0] and client.calls == 2


def test_retries_on_5xx_with_growing_wait_then_success():
    responses = [httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"x": 1})]
    client, clock = _client(lambda r: responses.pop(0), min_interval=0)
    assert client.get_json("/a") == {"x": 1}
    assert clock.slept == [1.0, 2.0]


def test_retry_after_is_honoured_and_not_waited_after_last_attempt():
    client, clock = _client(lambda r: httpx.Response(429, headers={"Retry-After": "7"}),
                            min_interval=0)  # fmt: skip
    with pytest.raises(HttpError) as err:
        client.get_json("/a")
    assert err.value.status == 429 and clock.slept == [7.0, 7.0]


def test_client_errors_are_not_retried():
    client, _ = _client(lambda r: httpx.Response(404), min_interval=0)
    with pytest.raises(HttpError, match="404"):
        client.get_json("/a")
    assert client.calls == 1


def test_transport_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("refusé")
        return httpx.Response(200, json={})

    client, _ = _client(handler, min_interval=0)
    assert client.get_json("/a") == {} and len(calls) == 3


def test_exhausted_quota_waits_for_reset_before_next_call():
    clock = Clock()
    headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(clock.now) + 30)}
    responses = [httpx.Response(200, json={}, headers=headers), httpx.Response(200, json={})]
    client, _ = _client(lambda r: responses.pop(0), clock=clock, min_interval=0)
    client.get_json("/a")
    client.get_json("/b")
    assert clock.slept == [30.0]


@pytest.mark.parametrize("body", [b"<html>proxy</html>", b"[1, 2]"])
def test_non_json_or_unexpected_body_raises(body):
    client, _ = _client(lambda r: httpx.Response(200, content=body), min_interval=0)
    with pytest.raises(HttpError):
        client.get_json("/a")
