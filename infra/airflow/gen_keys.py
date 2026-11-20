"""Ajoute à .env les secrets d'Airflow manquants (make airflow-keys). N'affiche JAMAIS de valeur.

- AIRFLOW_FERNET_KEY : chiffre les connexions et variables stockées par Airflow. Format Fernet =
  32 octets aléatoires en base64 « url-safe » (pas besoin du paquet cryptography pour la créer).
- AIRFLOW_SECRET_KEY : signe les cookies de session de l'interface web.
- AIRFLOW_ADMIN_USER / AIRFLOW_ADMIN_PASSWORD : compte de l'interface (mot de passe aléatoire).
- AIRFLOW_UID : UID de l'hôte, pour que les fichiers écrits par Airflow t'appartiennent.
Une valeur déjà présente n'est jamais remplacée.
"""

import base64
import os
import secrets
import sys
from pathlib import Path

env = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
if not env.is_file():
    sys.exit(f"{env} absent : lance d'abord `make setup`")
present = {line.split("=", 1)[0].strip() for line in env.read_text().splitlines() if "=" in line}
wanted = {
    "AIRFLOW_UID": str(os.getuid()),
    "AIRFLOW_FERNET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "AIRFLOW_SECRET_KEY": secrets.token_urlsafe(32),
    "AIRFLOW_ADMIN_USER": "admin",
    "AIRFLOW_ADMIN_PASSWORD": secrets.token_urlsafe(16),
}
added = [k for k in wanted if k not in present]
if added:
    with env.open("a", encoding="utf-8") as f:
        f.write("\n# --- Airflow (phase 6), généré par make airflow-keys ---\n")
        f.writelines(f"{k}={wanted[k]}\n" for k in added)
print(f"Ajouté à {env} : {', '.join(added) or 'rien (déjà présent)'}")
