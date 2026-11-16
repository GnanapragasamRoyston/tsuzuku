"""Point d'entrée de l'API Tsuzuku."""

from fastapi import FastAPI

app = FastAPI(title="Tsuzuku API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    # Liveness simple pour l'instant ; la vérification de la base arrivera en phase 5.
    return {"status": "ok"}
