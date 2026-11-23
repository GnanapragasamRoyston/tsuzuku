# API Tsuzuku. Contexte de build : la RACINE du dépôt (le backend dépend du paquet partagé
# packages/tsuzuku-ml). Lancement : make api-up (docker compose, profil « api »).

# --- Étape 1 : environnement Python construit avec uv ------------------------------------------
FROM python:3.11-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
# Bytecode précompilé (démarrage plus rapide), copie des fichiers (pas de liens vers le cache),
# et jamais de téléchargement d'un autre Python que celui de l'image.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY packages/tsuzuku-ml /app/packages/tsuzuku-ml
COPY backend/pyproject.toml backend/uv.lock ./
# Dépendances d'abord (couche mise en cache tant que le lockfile ne change pas), code ensuite.
RUN uv sync --frozen --no-dev --no-install-project --no-editable
COPY backend/app ./app
RUN uv sync --frozen --no-dev --no-editable

# --- Étape 2 : image finale, sans uv ni outils de build ----------------------------------------
FROM python:3.11-slim
# Utilisateur sans privilèges : une faille dans l'API ne donne pas root dans le conteneur.
RUN useradd --create-home --uid 10001 api
WORKDIR /app/backend
# Même chemin qu'à l'étape 1 : les scripts du venv (uvicorn) pointent vers ce Python.
COPY --from=build /app/backend/.venv /app/backend/.venv
COPY config/settings.yaml /app/config/settings.yaml
# Migrations du schéma app (service api-migrate : `alembic upgrade head`).
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
# Job de migration de production (`python -m app.migrate`, ADR 014) : schéma du pipeline PUIS
# Alembic. Fichiers SQL du pipeline copiés tels quels (une seule source, ADR 003).
COPY pipeline/src/tsuzuku_pipeline/db/schema_catalog.sql pipeline/src/tsuzuku_pipeline/db/schema_mart.sql /app/pipeline-schema/
# Dossier des modèles accessible en écriture à l'utilisateur de l'API : en production, les
# modèles y sont copiés depuis Cloud Storage au démarrage (MODELS_URI).
RUN mkdir -p /models && chown api /models
ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MODELS_DIR=/models \
    PIPELINE_SCHEMA_DIR=/app/pipeline-schema \
    ALEMBIC_CONFIG=/app/backend/alembic.ini \
    SETTINGS_FILE=/app/config/settings.yaml
USER api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
# --no-proxy-headers : X-Forwarded-For est toujours ignoré (un client peut l'écrire). En production,
# l'IP du visiteur arrive par X-Tsuzuku-Client-IP, crue seulement avec le secret du relais
# (TrustedProxyMiddleware, ADR 014) ; sans secret (dev), l'IP de la connexion (ADR 009).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
