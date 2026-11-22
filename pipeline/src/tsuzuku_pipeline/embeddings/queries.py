"""Requêtes sur les embeddings SANS numpy ni PyTorch : importables dans l'image Airflow (qui
n'installe que httpx, psycopg, python-dotenv et pyyaml, voir infra/airflow/Dockerfile)."""

import psycopg


def missing_count(conn: psycopg.Connection) -> int:
    """Œuvres sans embedding (contrôle qualité du DAG : rappelle de lancer make embeddings)."""
    return conn.execute(
        "SELECT count(*) FROM catalog.media m WHERE NOT EXISTS"
        " (SELECT 1 FROM catalog.media_embedding e WHERE e.media_id = m.id)"
    ).fetchone()[0]
