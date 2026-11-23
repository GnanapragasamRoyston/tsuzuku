# Ingestion de production (phase 11, ADR 014) : Cloud Run Job lancé par Cloud Scheduler.
#   jikan-daily (chaque jour) et anilist-weekly (chaque semaine), mêmes tâches que les DAG.
# Contexte de build : la RACINE du dépôt. Image légère : ni Airflow, ni PySpark, ni PyTorch ;
# mêmes dépendances que l'image Airflow (infra/airflow/Dockerfile), le reste du pipeline n'est
# pas importé par l'ingestion (vérifié par ci-airflow, qui charge les DAG avec ce même jeu).
FROM python:3.11-slim

RUN useradd --create-home --uid 10001 ingest
WORKDIR /opt/tsuzuku
COPY pipeline/pyproject.toml /tmp/tsuzuku/pipeline/pyproject.toml
COPY pipeline/src /tmp/tsuzuku/pipeline/src
RUN pip install --no-cache-dir "httpx>=0.27" "psycopg[binary]>=3.2" "python-dotenv>=1.0" "pyyaml>=6.0" \
    && pip install --no-cache-dir --no-deps /tmp/tsuzuku/pipeline \
    && rm -rf /tmp/tsuzuku
# Réglages et watchlist ; data/raw et reports/ sont éphémères (les rapports partent aussi dans
# les journaux). DATABASE_URL vient de Secret Manager.
COPY config/settings.yaml config/watchlist.yaml /opt/tsuzuku/config/
RUN mkdir -p /opt/tsuzuku/data /opt/tsuzuku/reports && chown -R ingest /opt/tsuzuku
ENV TSUZUKU_ROOT=/opt/tsuzuku PYTHONUNBUFFERED=1
USER ingest
ENTRYPOINT ["python", "-m", "tsuzuku_pipeline.ingestion.cli"]
CMD ["jikan-daily"]
