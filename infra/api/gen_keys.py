"""Ajoute à .env le secret des sessions de l'API s'il manque (make api-keys). N'affiche JAMAIS
la valeur.

JWT_SECRET signe les jetons de session (HS256) : 48 octets aléatoires (64 caractères), bien
au-delà des 32 octets minimum recommandés pour HMAC-SHA256. Le changer déconnecte tout le monde.
Une valeur déjà présente n'est jamais remplacée.
"""

import secrets
import sys
from pathlib import Path

env = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
if not env.is_file():
    sys.exit(f"{env} absent : lance d'abord `make setup`")
present = {line.split("=", 1)[0].strip() for line in env.read_text().splitlines() if "=" in line}
if "JWT_SECRET" in present:
    print(f"JWT_SECRET déjà présent dans {env} : rien à faire")
else:
    with env.open("a", encoding="utf-8") as f:
        f.write("\n# --- API (phase 7), généré par make api-keys ---\n")
        f.write(f"JWT_SECRET={secrets.token_urlsafe(48)}\n")
    print(f"JWT_SECRET ajouté à {env}")
