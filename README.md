# Tsuzuku 続く

> Suivi d'animes, mangas et manhwas qui recommande quoi regarder — et **prévient avant que tu décroches**.

Sous le capot : un pipeline Big Data sur 109 M d'interactions MyAnimeList (PySpark), une ingestion
quotidienne (Airflow), un modèle de churn (« risque de drop », scikit-learn), une recommandation
ALS (Spark MLlib), une API FastAPI et un front Next.js.

🚧 **En construction** — phase 1 terminée (données). Voir [docs/SPEC.md](docs/SPEC.md) pour le
cahier des charges et [docs/architecture.md](docs/architecture.md) pour l'architecture.

## Démarrage

Prérequis : WSL2 (ou Linux/macOS), Docker, `make`, [uv](https://docs.astral.sh/uv/), Java 17
(PySpark), un jeton Kaggle dans `~/.kaggle/access_token` (`chmod 600`).

```bash
make setup     # environnements Python + .env
make up        # Postgres 16 + pgvector
make db-check  # vérifie l'extension et les schémas
make data      # Kaggle → Parquet (staging/clean), filtre adulte, rapport qualité, échantillon
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

Dataset « Anime Recommendation Database 2020 » (Kaggle `hernan4444/anime-recommendation-database-2020`,
licence **CC0-1.0**), collecté sur MyAnimeList début 2020. Données fraîches via l'API Jikan et l'API
GraphQL AniList (phase 6).

- Dictionnaire, couches et règles de nettoyage : [docs/data.md](docs/data.md)
- Volumes et qualité, générés par `make data` : [reports/data_quality.md](reports/data_quality.md)
- Contenus adultes exclus partout (`Rating` en `Rx` ou genre `Hentai`) : [ADR 002](docs/decisions/002-donnees-brutes-parquet.md)

## Résultats

TODO: mesurer (phases 3 et 4 — tous les chiffres viendront de `reports/`).
