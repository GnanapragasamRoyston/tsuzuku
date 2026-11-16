# ADR 001 — Monorepo et outillage Python

**Date** : 2026-11-16 · **Statut** : accepté

## Contexte
Le projet mêle pipeline Data/ML (Spark, Airflow), API (FastAPI) et front (Next.js). Il doit rester
simple à relancer par un recruteur (`docker compose up` + `make`).

## Décisions
1. **Monorepo** (`pipeline/`, `backend/`, `frontend/`) : une seule CI, une seule doc, des changements
   transverses (ex. schéma de features partagé par l'entraînement et l'API) dans un seul commit.
2. **Un environnement Python par sous-projet**, gérés par **uv** (lockfile `uv.lock` par projet).
   PySpark et Airflow imposent des contraintes de versions lourdes qu'on isole du backend.
   uv plutôt que pip + venv : installation beaucoup plus rapide et lockfile natif reproductible.
3. **ruff** pour lint + formatage (remplace flake8, isort et black en un outil), config unique à la
   racine. Règles `S` (bandit) activées dès le départ.
4. **Développement sous WSL2** : PySpark est mal supporté sous Windows natif, et `make` n'y existe
   pas. Windows reste utilisé pour Power BI Desktop.
5. **docker-compose minimal** : on n'ajoute un service qu'à la phase qui en a besoin (Postgres
   maintenant, Airflow en phase 6). Postgres exposé sur `127.0.0.1:5433` uniquement.

## Alternatives écartées
- Poetry : plus lent, gestion des versions de Python moins intégrée.
- Un seul environnement pour tout : conflits de dépendances Airflow ↔ FastAPI quasi certains.
- Polyrepo : surcoût de coordination injustifié pour un projet solo.
