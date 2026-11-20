"""Mots de passe (argon2id) et jetons de session (JWT signé HS256), ADR 008.

Le jeton contient seulement l'id du compte et sa `token_version` : aucune donnée personnelle
(un JWT est signé, pas chiffré : son contenu se lit en base64).
"""

import datetime as dt

import jwt
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

COOKIE_NAME = "tsuzuku_session"
ALGORITHM = "HS256"
ISSUER = "tsuzuku"


class InvalidToken(Exception):
    """Jeton absent, mal formé, mal signé ou expiré (la cause exacte n'est jamais renvoyée)."""


class PasswordHasher:
    """argon2id avec les paramètres par défaut d'argon2-cffi (profil RFC 9106 « faible mémoire »).

    `verify(None, …)` vérifie contre un hash factice : une connexion avec un email inconnu prend
    le même temps qu'avec un mauvais mot de passe. Sans ça, la durée de la réponse révélerait
    quels emails ont un compte.
    """

    def __init__(self) -> None:
        self._argon2 = _Argon2()
        self._dummy_hash = self._argon2.hash("mot de passe factice, jamais attribué")

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash or self._dummy_hash, password) and (
                password_hash is not None
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        # Vrai si les paramètres d'argon2 ont été renforcés depuis le hachage : on rehache à la
        # prochaine connexion réussie (le seul moment où l'on connaît le mot de passe en clair).
        return self._argon2.check_needs_rehash(password_hash)


def create_token(user_id: int, token_version: int, secret: str, ttl_hours: int) -> str:
    now = dt.datetime.now(dt.UTC)
    claims = {
        "sub": str(user_id),
        "tv": token_version,
        "iss": ISSUER,
        "iat": now,
        "exp": now + dt.timedelta(hours=ttl_hours),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> tuple[int, int]:
    """(user_id, token_version) d'un jeton valide ; InvalidToken sinon.

    `algorithms` fixé : un jeton « alg: none » ou signé avec un autre algorithme est refusé.
    """
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM], issuer=ISSUER,
                            options={"require": ["sub", "tv", "exp", "iat", "iss"]})  # fmt: skip
        return int(claims["sub"]), int(claims["tv"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidToken from exc
