# Tsuzuku — commandes du projet. À lancer depuis WSL2 / Linux / macOS.
# `make help` liste les commandes disponibles.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help setup up down db-check lint format test audit \
        data spark train figures reco api api-keys api-up api-down web web-test web-e2e covers covers-report covers-review covers-approve covers-reject migrate \
        airflow-keys airflow-up airflow-down airflow-test airflow-trigger

# packages/tsuzuku-ml : code ML partagé par le pipeline et l'API (ADR 006).
PY_PROJECTS := packages/tsuzuku-ml pipeline backend

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
	@for p in $(PY_PROJECTS); do (cd $$p && uv export --no-hashes --no-emit-local --format requirements-txt -q | uv run pip-audit -r /dev/stdin) || exit 1; done
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

# --- API (phase 5) ----------------------------------------------------------
# Nécessite `make up` (base) et les artefacts de `make train` / `make reco` dans models/.
# Documentation interactive (Swagger) : http://localhost:8000/docs
api: ## [phase 5] Lance l'API en local (rechargement auto)
	cd backend && uv run uvicorn app.main:create_app --factory --reload --no-proxy-headers

api-keys: ## [phase 7] Ajoute à .env le secret des sessions (JWT_SECRET), sans l'afficher
	python3 infra/api/gen_keys.py .env

api-up: ## [phase 5] Applique les migrations et lance l'API dans Docker (http://localhost:8000/docs)
	@grep -q "^JWT_SECRET=." .env || { echo "JWT_SECRET absent de .env : lance make api-keys"; exit 1; }
	docker compose --profile api up -d --build --wait api

# --- Comptes (phase 7) -------------------------------------------------------
# Schéma app (comptes, listes) géré par Alembic ; catalog et mart restent au pipeline (ADR 008).
# Prérequis : catalogue chargé (make spark) : les tables app ont des FK vers catalog.media.
migrate: ## [phase 7] Applique les migrations Alembic du schéma app (base du .env)
	cd backend && uv run alembic upgrade head

api-down: ## Arrête le conteneur de l'API
	docker compose --profile api stop api

# --- Airflow (phase 6) -------------------------------------------------------
# Interface : http://localhost:8080 (identifiants dans .env : AIRFLOW_ADMIN_USER / _PASSWORD).
AIRFLOW := docker compose --profile airflow
AIRFLOW_VARS := AIRFLOW_UID AIRFLOW_FERNET_KEY AIRFLOW_SECRET_KEY AIRFLOW_ADMIN_PASSWORD

airflow-keys: ## [phase 6] Ajoute à .env les secrets d'Airflow manquants (sans les afficher)
	python3 infra/airflow/gen_keys.py .env

airflow-up: ## [phase 6] Construit et lance Airflow (webserver + scheduler) dans Docker
	@for v in $(AIRFLOW_VARS); do grep -q "^$$v=." .env || { echo "$$v absent de .env : lance make airflow-keys"; exit 1; }; done
	mkdir -p data/raw/jikan data/raw/anilist reports/ingestion
	$(AIRFLOW) up -d --build --wait airflow-webserver airflow-scheduler

airflow-down: ## Arrête Airflow (la base et l'API ne sont pas touchées)
	$(AIRFLOW) stop airflow-webserver airflow-scheduler

# Base SQLite jetable et sans vérification de connexion : le test ne dépend ni de Postgres ni de la
# base « airflow » (comme en CI).
airflow-test: ## [phase 6] Vérifie dans l'image que les DAG se chargent sans erreur
	$(AIRFLOW) run --rm --no-deps -e CONNECTION_CHECK_MAX_COUNT=0 \
		-e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////tmp/airflow.db \
		-v ./pipeline/tests/test_dags.py:/opt/tsuzuku/dagtests/test_dags.py:ro \
		airflow-scheduler bash -c "airflow db migrate >/dev/null && pip install -q pytest \
		&& python -m pytest -q -p no:cacheprovider /opt/tsuzuku/dagtests"

# Déclencher un DAG tout de suite : make airflow-trigger DAG=anilist_catalog_sync
airflow-trigger: ## [phase 6] Déclenche un DAG (DAG=jikan_daily_ingest ou anilist_catalog_sync)
	$(AIRFLOW) exec airflow-scheduler airflow dags trigger $(DAG)

# --- Front (phase 8) ---------------------------------------------------------
# Node 24 LTS (nvm) dans WSL. Le front relaie /api/* vers l'API (make api ou make api-up).
# NODE charge nvm si node n'est pas déjà dans le PATH (terminal ouvert avant l'installation,
# shell non interactif) : sinon WSL trouverait le npm de Windows, qui échoue sur un chemin WSL.
NODE := command -v node >/dev/null || . "$$HOME/.nvm/nvm.sh";

covers: ## [phase 8] Jaquettes des animes depuis AniList (idMal) : manquantes et petites, sans Airflow
	cd pipeline && uv run python -m tsuzuku_pipeline.ingestion.cli covers

covers-report: ## [jaquettes] Couverture par source, type et popularité → reports/covers_coverage.json
	cd pipeline && uv run python -m tsuzuku_pipeline.ingestion.cli covers-report

covers-review: ## [jaquettes] Jaquettes proposées en attente de validation
	cd backend && uv run python -m scripts.covers_review list

covers-approve: ## [jaquettes] Valide une jaquette proposée (ID=12)
	@test -n "$(ID)" || (echo "Usage : make covers-approve ID=12" && exit 1)
	cd backend && uv run python -m scripts.covers_review approve $(ID)

covers-reject: ## [jaquettes] Refuse une jaquette proposée (ID=13)
	@test -n "$(ID)" || (echo "Usage : make covers-reject ID=13" && exit 1)
	cd backend && uv run python -m scripts.covers_review reject $(ID)

web: ## [phase 8] Lance le front Next.js (http://localhost:3000) ; make api dans un autre terminal
	@$(NODE) cd frontend && (curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/health \
		|| echo "⚠ API injoignable sur :8000 : lance « make api » dans un autre terminal") \
		&& npm run dev

web-test: ## [phase 8] Lint, types et tests Vitest du front
	@$(NODE) cd frontend && npm run lint && npm run typecheck && npm test

web-e2e: ## [phase 8] Parcours de bout en bout (Playwright + axe) sur une base de test dédiée
	@$(NODE) cd frontend && npx playwright test
