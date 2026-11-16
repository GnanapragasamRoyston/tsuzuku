-- Exécuté au premier démarrage du conteneur Postgres (volume vide).
-- Les tables arrivent plus tard : mart/catalog en phase 2 (Spark), app en phase 7 (Alembic).

CREATE EXTENSION IF NOT EXISTS vector;

-- Trois schémas séparés : données de référence, données utilisateurs, analytique.
-- La séparation permet des droits distincts (ex. Power BI en lecture seule sur mart).
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS mart;
