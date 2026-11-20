"""Comptes : inscription, connexion, déconnexion, jetons (phase 7, ADR 008)."""

import datetime as dt
import logging

import jwt
import psycopg
import pytest

from app.core.security import COOKIE_NAME
from tests.conftest import PASSWORD, TEST_JWT_SECRET, register

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_users")]


def _cookie_header(response) -> str:
    return next(
        v
        for k, v in response.headers.multi_items()
        if k == "set-cookie" and v.startswith(COOKIE_NAME)
    )


def _token(client) -> str:
    return client.cookies[COOKIE_NAME]


# --- Inscription ---------------------------------------------------------------------------------
def test_register_creates_account_and_logs_in(make_client, pg_url):
    client = make_client()
    r = register(client, pseudo="royston", email="Royston@Example.com")
    assert r.status_code == 201
    body = r.json()
    assert body["pseudo"] == "royston" and body["email"] == "royston@example.com"
    assert "password" not in str(body) and "hash" not in str(body)
    # Cookie de session : invisible du JavaScript, HTTPS seulement, pas envoyé par un autre site.
    cookie = _cookie_header(r).lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "path=/" in cookie and "max-age=" in cookie
    assert client.get("/me").json()["pseudo"] == "royston"
    with psycopg.connect(pg_url) as conn:
        stored = conn.execute("SELECT password_hash FROM app.users").fetchone()[0]
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


@pytest.mark.parametrize(
    "change",
    [
        {"email": "ROYSTON@example.com"},  # même email, autre casse
        {"pseudo": "royston", "email": "autre@example.com"},
    ],
)
def test_register_rejects_duplicates(make_client, change):
    client = make_client()
    assert register(client, pseudo="royston").status_code == 201
    payload = {"pseudo": "autre", "email": "royston@example.com", **change}
    r = make_client().post("/auth/register", json={**payload, "password": PASSWORD})
    assert r.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "pas-un-email"},
        {"pseudo": "Ro"},  # trop court
        {"pseudo": "Royston"},  # majuscule : les pseudos sont en minuscules (URL de profil)
        {"pseudo": "roy ston"},
        {"password": "court"},
        {"password": "x" * 129},  # borne le coût du hachage
        {"extra": "champ inconnu"},
    ],
)
def test_register_validates_input(make_client, payload):
    base = {"email": "a@example.com", "pseudo": "royston", "password": PASSWORD}
    r = make_client().post("/auth/register", json={**base, **payload})
    assert r.status_code == 422
    # La réponse d'erreur ne renvoie jamais le mot de passe saisi.
    assert PASSWORD not in r.text and "x" * 129 not in r.text


# --- Connexion -----------------------------------------------------------------------------------
def test_login_sets_session_cookie(make_client):
    register(make_client())
    client = make_client()
    r = client.post("/auth/login", json={"email": "ROYSTON@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["pseudo"] == "royston"
    assert "httponly" in _cookie_header(r).lower()
    assert client.get("/me").status_code == 200


def test_login_errors_do_not_reveal_which_part_is_wrong(make_client):
    register(make_client())
    client = make_client()
    wrong_password = client.post(
        "/auth/login", json={"email": "royston@example.com", "password": "mauvais-mdp"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "inconnu@example.com", "password": PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert COOKIE_NAME not in client.cookies


def test_login_is_rate_limited(make_client):
    register(make_client())
    client = make_client()
    bad = {"email": "royston@example.com", "password": "mauvais-mdp"}
    for _ in range(5):
        assert client.post("/auth/login", json=bad).status_code == 401
    # 6e essai dans la fenêtre : refusé, même avec le BON mot de passe.
    r = client.post("/auth/login", json={**bad, "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_login_limit_counts_per_ip_across_emails(make_client):
    """Changer d'email à chaque essai ne contourne pas la limite : l'IP a son propre compteur
    (le compteur par email, lui, est testé dans test_security.py)."""
    client = make_client(auth=_auth(login_limit={"max_attempts": 2, "window_s": 300}))
    for email in ("a@example.com", "b@example.com"):
        client.post("/auth/login", json={"email": email, "password": "mauvais-mdp"})
    r = client.post("/auth/login", json={"email": "c@example.com", "password": "mauvais-mdp"})
    assert r.status_code == 429


def test_register_is_rate_limited(make_client):
    client = make_client(auth=_auth(register_limit={"max_attempts": 2, "window_s": 3600}))
    for i in range(2):
        assert register(client, pseudo=f"user{i}").status_code == 201
    assert register(client, pseudo="user9").status_code == 429


# --- Session -------------------------------------------------------------------------------------
def test_me_requires_a_session(make_client):
    assert make_client().get("/me").status_code == 401


def test_logout_revokes_existing_tokens(user_client, make_client):
    token = _token(user_client)
    r = user_client.post("/auth/logout")
    assert r.status_code == 204
    assert user_client.get("/me").status_code == 401
    # Le jeton copié avant la déconnexion ne marche plus non plus (token_version).
    other = make_client()
    other.cookies.set(COOKIE_NAME, token)
    assert other.get("/me").status_code == 401


def test_logout_without_session_is_harmless(make_client):
    assert make_client().post("/auth/logout").status_code == 204


def _forged(key=TEST_JWT_SECRET, algorithm="HS256", drop=(), **claims) -> str:
    """Jeton aux claims COMPLETS, modifié sur un seul point : chaque cas refusé l'est pour la
    raison testée (revue : sans exp/iat, un jeton était refusé avant même la signature)."""
    now = dt.datetime.now(dt.UTC)
    base = {"sub": "1", "tv": 0, "iss": "tsuzuku", "iat": now, "exp": now + dt.timedelta(hours=1)}
    payload = {k: v for k, v in {**base, **claims}.items() if k not in drop}
    return jwt.encode(payload, key, algorithm=algorithm)


@pytest.mark.parametrize(
    "token",
    [
        "pas-un-jeton",
        _forged(exp=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)),  # expiré
        _forged(tv=1),  # mauvaise version
        _forged(sub="999"),  # compte inexistant
        _forged(key="autre-secret-" + "y" * 40),  # mauvaise signature
        _forged(key=None, algorithm="none"),  # signature absente
        _forged(iss="ailleurs"),  # émis par un autre service
        _forged(drop=("iss",)),
        _forged(drop=("exp",)),
    ],
)
def test_invalid_tokens_are_rejected(user_client, token):
    user_client.cookies.set(COOKIE_NAME, token)
    assert user_client.get("/me").status_code == 401


def test_valid_forged_token_shape_matches_real_one(user_client):
    # Témoin des tests ci-dessus : un jeton bien signé pour le compte 1 (version 0) est accepté.
    user_client.cookies.set(COOKIE_NAME, _forged())
    assert user_client.get("/me").status_code == 200


def test_secrets_never_reach_the_logs(make_client, caplog):
    caplog.set_level(logging.DEBUG)
    client = make_client()
    register(client, pseudo="royston", email="royston@example.com")
    client.post("/auth/login", json={"email": "royston@example.com", "password": "mauvais-mdp"})
    logs = caplog.text
    assert PASSWORD not in logs and "mauvais-mdp" not in logs
    assert "royston@example.com" not in logs and TEST_JWT_SECRET not in logs


def test_accounts_unavailable_without_secret(make_client):
    # Sans JWT_SECRET, l'API démarre (catalogue, démo) mais refuse les comptes : 503, pas 500.
    client = make_client(jwt_secret=None)
    assert register(client).status_code == 503
    assert client.get("/me").status_code == 503
    assert client.get("/health").status_code == 200


def _auth(**changes):
    from app.core.config import REPO_ROOT, load_rules

    auth = load_rules(REPO_ROOT / "config" / "settings.yaml").auth
    return auth.model_copy(
        update={k: type(getattr(auth, k)).model_validate(v) for k, v in changes.items()}
    )


def test_validation_errors_never_echo_the_input(make_client):
    secret_like = "p" * 1025  # au-delà de la borne du schéma
    r = make_client().post("/auth/login", json={"email": "a@example.com", "password": secret_like})
    assert r.status_code == 422
    assert secret_like not in r.text and '"input"' not in r.text
    assert r.json()["detail"][0]["loc"] == ["body", "password"]


def test_wildcard_cors_is_refused_at_startup(pg_url, models_dir):
    from app.core.config import REPO_ROOT, Settings
    from app.main import create_app

    settings = Settings(database_url=pg_url, models_dir=models_dir, cors_origins=["*"],
                        settings_file=REPO_ROOT / "config" / "settings.yaml")  # fmt: skip
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        create_app(settings)
