"""X-Forwarded-For ne doit jamais être cru par l'API (ADR 009, revue de sécurité phase 8).

Le relais du front transmet cet en-tête tel que le client l'a écrit : uvicorn s'y fiait par
défaut (requêtes venant de 127.0.0.1), ce qui permettait de changer d'« IP » à chaque requête et
de contourner la limite de tentatives. Chaque façon de lancer l'API doit le désactiver.
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request

from app.core.config import REPO_ROOT


@pytest.mark.parametrize(("path", "flag"), [
    ("Makefile", "--no-proxy-headers"),
    ("backend/Dockerfile", '"--no-proxy-headers"'),
    ("backend/scripts/e2e_api.py", "proxy_headers=False"),
])  # fmt: skip
def test_every_launcher_disables_proxy_headers(path, flag):
    assert flag in (REPO_ROOT / path).read_text(encoding="utf-8")


def test_uvicorn_without_proxy_headers_ignores_forwarded_for():
    """Le réglage fait bien ce qu'on croit : l'IP vue reste celle de la connexion."""
    app = FastAPI()

    @app.get("/ip")
    def ip(request: Request) -> dict:
        return {"ip": request.client.host}

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error",
                                           proxy_headers=False))  # fmt: skip
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        r = httpx.get(f"http://127.0.0.1:{port}/ip", headers={"X-Forwarded-For": "203.0.113.9"})
        assert r.json() == {"ip": "127.0.0.1"}
    finally:
        server.should_exit = True
        thread.join(timeout=5)
