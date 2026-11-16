# Tsuzuku 続く

> Suivi d'animes, mangas et manhwas qui recommande quoi regarder — et **prévient avant que tu décroches**.

Sous le capot : un pipeline Big Data sur 109 M d'interactions MyAnimeList (PySpark), une ingestion
quotidienne (Airflow), un modèle de churn (« risque de drop », scikit-learn), une recommandation
ALS (Spark MLlib), une API FastAPI et un front Next.js.

🚧 **En construction** — phase 0 (setup du monorepo). Voir [docs/SPEC.md](docs/SPEC.md) pour le
cahier des charges et [docs/architecture.md](docs/architecture.md) pour l'architecture.

## Démarrage

Prérequis : WSL2 (ou Linux/macOS), Docker, `make`, [uv](https://docs.astral.sh/uv/).

```bash
make setup     # environnements Python + .env
make up        # Postgres 16 + pgvector
make db-check  # vérifie l'extension et les schémas
make lint test # qualité
make help      # toutes les commandes
```

## Structure

| Dossier | Contenu |
|---|---|
| `pipeline/` | Data/ML : Spark, Airflow, entraînement |
| `backend/` | API FastAPI |
| `frontend/` | Next.js (phase 8) |
| `config/` | `settings.yaml` (seeds, seuils, chemins), `watchlist.yaml` |
| `infra/` | scripts d'init Postgres |
| `docs/` | spec, architecture, décisions (ADR), journal d'apprentissage |

## Données

Dataset « Anime Recommendation Database 2020 » (Kaggle, hernan4444) — source et licence détaillées
en phase 1. Données fraîches via l'API Jikan et l'API GraphQL AniList.

## Résultats

TODO: mesurer (phases 3 et 4 — tous les chiffres viendront de `reports/`).
