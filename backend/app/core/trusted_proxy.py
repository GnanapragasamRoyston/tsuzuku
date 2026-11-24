"""Relais de confiance (phase 11, ADR 014).

En production, le navigateur ne parle qu'au front (Vercel), qui relaie /api/* vers l'API (Cloud
Run, URL publique). Le relais ajoute deux en-têtes : un secret partagé (X-Tsuzuku-Proxy) et l'IP
du visiteur (X-Tsuzuku-Client-IP), lue par le front dans l'en-tête que pose la plateforme.
- Sans le bon secret : 403. Personne ne peut appeler l'API en direct en se faisant passer pour
  le relais, ni choisir son « IP » pour contourner la limite de connexion.
- /health et /health/ready restent ouverts : la sonde de disponibilité n'a pas le secret.
- Une IP mal formée n'est pas crue : on garde l'IP de la connexion.
"""

import hmac
import ipaddress
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SECRET_HEADER = b"x-tsuzuku-proxy"
CLIENT_IP_HEADER = b"x-tsuzuku-client-ip"
OPEN_PATHS = frozenset({"/health", "/health/ready"})
logger = logging.getLogger("tsuzuku_api")


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


class TrustedProxyMiddleware:
    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.secret = secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        # Comparaison à temps constant : la durée ne révèle rien du secret.
        if not hmac.compare_digest(headers.get(SECRET_HEADER, b""), self.secret):
            await JSONResponse({"detail": "Accès direct à l'API refusé"}, status_code=403)(
                scope, receive, send
            )
            return
        ip = _valid_ip(headers.get(CLIENT_IP_HEADER, b"").decode("latin-1"))
        if ip:
            scope.setdefault("state", {})["client_ip"] = ip
        elif scope["path"].startswith("/auth/"):
            # Relais hors Vercel ou en-tête perdu : la limite de connexion redevient globale
            # (IP du frontal Google). Signalé seulement là où l'IP sert (connexion, inscription) :
            # les pages rendues par le serveur Next n'ont pas de visiteur, c'est normal (36
            # avertissements inutiles en 10 minutes, mesuré en production). Sans l'adresse.
            logger.warning("IP du visiteur absente ou invalide derrière le relais (%s)",
                           scope["path"])  # fmt: skip
        await self.app(scope, receive, send)
