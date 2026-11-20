# Image Airflow de Tsuzuku (phase 6). Contexte de build : la RACINE du dépôt.
# Airflow 2.11 (dernière version 2.x, SPEC : Airflow 2.x) + le paquet `pipeline` SANS PySpark :
# l'ingestion n'utilise que httpx, psycopg et pyyaml (garanti par tests/test_ingestion_no_spark).
ARG AIRFLOW_VERSION=2.11.0
FROM apache/airflow:${AIRFLOW_VERSION}-python3.11
ARG AIRFLOW_VERSION

COPY --chown=airflow:root pipeline/pyproject.toml /tmp/tsuzuku/pipeline/pyproject.toml
COPY --chown=airflow:root pipeline/src /tmp/tsuzuku/pipeline/src

# Le fichier de contraintes d'Airflow fige les versions compatibles : une dépendance ajoutée ne
# peut pas casser Airflow. Le paquet pipeline est installé avec --no-deps (sinon pip tirerait
# PySpark, scikit-learn, etc.) ; ses dépendances réellement utilisées sont listées à la main.
RUN pip install --no-cache-dir \
        "apache-airflow==${AIRFLOW_VERSION}" \
        "httpx" "psycopg[binary]>=3.2" "python-dotenv" "pyyaml" \
        --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.11.txt" \
    && pip install --no-cache-dir --no-deps /tmp/tsuzuku/pipeline

# config/, data/raw et reports/ sont montés ici par docker-compose (voir TSUZUKU_ROOT).
ENV TSUZUKU_ROOT=/opt/tsuzuku
