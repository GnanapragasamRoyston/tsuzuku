# Tsuzuku — commandes du projet. À lancer depuis WSL2 / Linux / macOS.
# `make help` liste les commandes disponibles.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help setup up down db-check lint format test audit \
        data spark train figures reco api web migrate

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

# --- Marts (phase 2) --------------------------------------------------------
# Nécessite `make data` puis `make up`. Les marts sont recalculés seulement s'ils sont périmés ;
# le chargement Postgres est rejoué à chaque fois (idempotent).
spark: ## [phase 2] Transformations Spark -> marts Postgres (catalogue + drop + rétention)
	cd pipeline && uv run python -m tsuzuku_pipeline.spark_cli $(ARGS)

# --- Modèle de drop (phase 3) -----------------------------------------------
# Nécessite `make data` (et `make up` pour l'enregistrement du run). Features recalculées
# seulement si périmées ; un changement de grille réentraîne sans relancer Spark.
train: ## [phase 3] Modèle de drop : features Spark, 3 modèles sklearn, métriques, artefact
	cd pipeline && uv run python -m tsuzuku_pipeline.train_cli $(ARGS)

# Étapes : prepare (Spark : filtre, split, masquage) → fit (grille ALS, fold-in, métriques,
# facteurs) → register (mart.model_runs). Même logique de fraîcheur que `make train`.
reco: ## [phase 4] Reco ALS : baseline popularité vs ALS explicite/implicite, fold-in, facteurs
	cd pipeline && uv run python -m tsuzuku_pipeline.reco_cli $(ARGS)

# --- Chiffres clés ------------------------------------------------------------
# Regroupe les chiffres des rapports générés (aucun calcul, aucune saisie à la main) pour export.
figures: ## Chiffres clés de toutes les phases -> reports/key_figures.{json,md}
	cd pipeline && uv run python -m tsuzuku_pipeline.key_figures

# --- Phases suivantes (pas encore implémentées) ----------------------------
api: ## [phase 5] Lance l'API FastAPI en local
	cd backend && uv run uvicorn app.main:app --reload
web: ## [phase 8] Lance le front Next.js
	@echo "Pas encore implémenté (phase 8)"; exit 1
migrate: ## [phase 7] Migrations Alembic
	@echo "Pas encore implémenté (phase 7)"; exit 1
