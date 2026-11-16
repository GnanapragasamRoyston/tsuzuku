# Tsuzuku — commandes du projet. À lancer depuis WSL2 / Linux / macOS.
# `make help` liste les commandes disponibles.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help setup up down db-check lint format test audit \
        data spark train reco api web migrate

PY_PROJECTS := pipeline backend

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# --- Environnement ---------------------------------------------------------
setup: ## Installe les environnements Python (uv) et crée .env si absent
	@test -f .env || (cp .env.example .env && echo ".env créé depuis .env.example : pense à changer le mot de passe")
	@for p in $(PY_PROJECTS); do (cd $$p && uv sync --python 3.11) || exit 1; done

up: ## Démarre les services Docker (Postgres + pgvector)
	docker compose up -d --wait

down: ## Arrête les services Docker (les données sont conservées dans le volume)
	docker compose down

db-check: ## Vérifie que pgvector et les schémas catalog/app/mart existent
	docker compose exec -T db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v ON_ERROR_STOP=1 -tA \
		-c "SELECT extname FROM pg_extension WHERE extname = '"'"'vector'"'"';" \
		-c "SELECT nspname FROM pg_namespace WHERE nspname IN ('"'"'catalog'"'"','"'"'app'"'"','"'"'mart'"'"') ORDER BY 1;"'

# --- Qualité ---------------------------------------------------------------
lint: ## ruff (lint + format check) sur pipeline et backend
	@for p in $(PY_PROJECTS); do \
		(cd $$p && uv run ruff check . && uv run ruff format --check .) || exit 1; done

format: ## Formate le code Python avec ruff
	@for p in $(PY_PROJECTS); do (cd $$p && uv run ruff check --fix . && uv run ruff format .); done

test: ## Lance pytest sur pipeline et backend
	@for p in $(PY_PROJECTS); do (cd $$p && uv run pytest) || exit 1; done

audit: ## Audit de sécurité des dépendances (pip-audit) + bandit sur le backend
	@for p in $(PY_PROJECTS); do (cd $$p && uv export --no-hashes --format requirements-txt -q | uv run pip-audit -r /dev/stdin) || exit 1; done
	cd backend && uv run bandit -q -r app

# --- Données (phase 1) ----------------------------------------------------
# Idempotent : les étapes déjà faites sont sautées. Refaire tout : make data ARGS=--force
# Une seule étape : make data ARGS="--step quality --force"
data: ## [phase 1] Téléchargement Kaggle, Parquet, filtre adulte, rapport qualité
	cd pipeline && uv run python -m tsuzuku_pipeline.data_cli $(ARGS)

# --- Phases suivantes (pas encore implémentées) ----------------------------
spark: ## [phase 2] Transformations Spark -> marts Postgres
	@echo "Pas encore implémenté (phase 2)"; exit 1
train: ## [phase 3] Entraînement du modèle de drop
	@echo "Pas encore implémenté (phase 3)"; exit 1
reco: ## [phase 4] Entraînement ALS
	@echo "Pas encore implémenté (phase 4)"; exit 1
api: ## [phase 5] Lance l'API FastAPI en local
	cd backend && uv run uvicorn app.main:app --reload
web: ## [phase 8] Lance le front Next.js
	@echo "Pas encore implémenté (phase 8)"; exit 1
migrate: ## [phase 7] Migrations Alembic
	@echo "Pas encore implémenté (phase 7)"; exit 1
