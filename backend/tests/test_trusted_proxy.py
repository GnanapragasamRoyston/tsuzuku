"""Relais de confiance (phase 11, ADR 014) : en production, l'API n'accepte que les requêtes du
front (en-tête secret X-Tsuzuku-Proxy) et ne croit l'IP du visiteur (X-Tsuzuku-Client-IP) que
si ce secret est valide. Résout la limite de l'ADR 009 (limite de connexion devenue globale).
"""

import pytest

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]

SECRET = "secret-du-relais-de-test-" + "x" * 40


def _login(client, email, ip=None, secret=SECRET):
    headers = {"X-Tsuzuku-Proxy": secret} if secret else {}
    if ip:
        headers["X-Tsuzuku-Client-IP"] = ip
    return client.post("/auth/login", json={"email": email, "password": "mauvais-mot-de-passe"},
                       headers=headers)  # fmt: skip


@pytest.fixture
def proxied(make_client):
    return make_client(proxy_secret=SECRET)


def test_direct_calls_are_refused_when_a_proxy_secret_is_set(proxied):
    assert proxied.get("/media/popular?kind=anime").status_code == 403
    wrong = proxied.get("/media/popular?kind=anime", headers={"X-Tsuzuku-Proxy": "faux"})
    assert wrong.status_code == 403
    ok = proxied.get("/media/popular?kind=anime", headers={"X-Tsuzuku-Proxy": SECRET})
    assert ok.status_code == 200


def test_health_stays_open_for_the_uptime_check(proxied):
    assert proxied.get("/health").status_code == 200
    assert proxied.get("/health/ready").status_code in (200, 503)  # sans secret : pas 403


def test_login_limit_is_per_visitor_ip_behind_the_proxy(proxied):
    # 5 échecs depuis la même IP (emails différents : seule la limite par IP joue) → bloqué…
    for i in range(5):
        assert _login(proxied, f"a{i}@example.com", ip="203.0.113.1").status_code == 401
    assert _login(proxied, "a9@example.com", ip="203.0.113.1").status_code == 429
    # … mais un autre visiteur n'est pas puni pour lui (la limite n'est plus globale).
    assert _login(proxied, "b@example.com", ip="203.0.113.2").status_code == 401


def test_a_malformed_client_ip_is_not_trusted(proxied):
    for i in range(5):
        _login(proxied, f"c{i}@example.com", ip=f"pas-une-ip-{i}")
    # Toutes ces valeurs invalides retombent sur la même IP de connexion : la limite tient.
    assert _login(proxied, "c9@example.com", ip="encore-autre-chose").status_code == 429


def test_without_proxy_secret_the_client_ip_header_is_ignored(make_client):
    client = make_client()  # dev, tests, E2E : pas de secret configuré
    for i in range(5):
        _login(client, f"d{i}@example.com", ip=f"198.51.100.{i}", secret=None)
    # Changer d'« IP » à chaque essai ne contourne rien : l'en-tête n'est pas cru.
    assert _login(client, "d9@example.com", ip="198.51.100.99", secret=None).status_code == 429


def test_a_missing_client_ip_behind_the_proxy_is_logged(proxied, caplog):
    # Secret valide mais pas d'IP (relais hors Vercel) : la limite redeviendrait globale, sans
    # bruit. On le signale dans les journaux (sans l'adresse) pour que ça se voie.
    with caplog.at_level("WARNING", logger="tsuzuku_api"):
        _login(proxied, "e@example.com", ip=None)
    assert any("IP du visiteur absente" in r.getMessage() for r in caplog.records)
