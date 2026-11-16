# CLAUDE.md — Tsuzuku

## Le projet en une phrase
**Tsuzuku** (続く, « à suivre ») : une appli web de suivi d'animes, mangas et manhwas — façon Letterboxd — qui recommande quoi regarder ou lire et **prévient avant que tu décroches** (risque de drop, épisode critique). Elle repose sur un pipeline Big Data : 109 M d'interactions MyAnimeList traitées avec PySpark, ingestion quotidienne via Airflow, modèles scikit-learn et Spark MLlib, API FastAPI, front Next.js, déployée sur le cloud.

Cahier des charges complet : `docs/SPEC.md`. Lis-le avant toute nouvelle phase.

## Qui pilote
Royston, étudiant ingénieur Big Data & ML (EFREI), profil data avec des bases solides en dev web. Il dirige, tu codes. Il doit pouvoir **expliquer chaque brique en entretien** : c'est un projet portfolio pour décrocher une alternance Data/ML. **Priorité absolue : la partie Data/ML** (phases 0 à 6) avant l'appli web.

## Règles de travail (obligatoires)
1. **Une phase à la fois** (`docs/SPEC.md` § 10). Ne commence jamais la phase suivante sans validation de Royston.
2. Workflow par phase : `/plan` → attendre validation → `/tdd` → `/code-review` → corriger les CRITICAL/HIGH → commit. Pour le front : `/e2e` sur les parcours clés.
3. Après chaque phase, ajoute une entrée dans `docs/LEARNING.md` (format en bas).
4. Code commenté en **français** sur le *pourquoi*. Noms de variables/fonctions en anglais.
5. **Aucun chiffre inventé.** Toute métrique du README vient d'un fichier généré (`reports/*.json`, sorties Spark). Sinon : `TODO: mesurer`.
6. Ne devine jamais un identifiant MAL ou AniList : cherche-le via l'API et note-le.
7. Ne lis jamais `animelist.csv` en entier avec pandas (≈ 109 M lignes) : PySpark, ou échantillon.
8. Secrets uniquement dans `.env` (jamais commité). `.env.example` à jour.
9. Toute décision technique non triviale → ADR court dans `docs/decisions/NNN-titre.md`.
10. Sécurité : mots de passe hachés (argon2), jamais de secret dans les logs, validation de toutes les entrées, dépendances auditées en CI.
11. Réponds à Royston en français.
12. Ne jamais ajouter de ligne `Co-Authored-By` ni de mention de Claude dans les commits ou les PR.

## Organisation du monorepo
- `pipeline/` — Data/ML Python (Spark, Airflow, entraînement)
- `backend/` — API FastAPI (auth, listes, catalogue, recos, risque de drop)
- `frontend/` — Next.js (TypeScript)
- `docs/`, `config/`, `reports/`, `powerbi/` à la racine

## Commandes utiles
- `make setup` · `make up` / `make down` · `make data` · `make spark` · `make train` · `make reco`
- `make api` · `make web` · `make test` · `make lint` · `make migrate`

## Stack
Python 3.11 · PySpark 3.5 (Java 17) · Spark MLlib (ALS) · scikit-learn · Apache Airflow 2.x · PostgreSQL 16 + pgvector · SQLAlchemy 2 + Alembic · FastAPI · sentence-transformers · Next.js (App Router, TypeScript) · Tailwind CSS · shadcn/ui · TanStack Query · pytest · Vitest · Playwright · ruff · Docker Compose · GitHub Actions · Google Cloud Run + Cloud Storage · Neon (Postgres managé) · Vercel · Power BI (fait à la main par Royston).

## Format d'une entrée LEARNING.md
```
## Phase N — Titre (date)
**Ce qui a été construit :** 3 lignes max.
**Concepts clés :** chaque concept expliqué en 2-3 phrases simples.
**Pourquoi ce choix :** alternatives écartées et raison.
**3 questions d'entretien possibles + réponses courtes.**
```
