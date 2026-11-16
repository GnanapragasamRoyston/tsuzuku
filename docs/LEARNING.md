# Journal d'apprentissage — Tsuzuku

Une entrée par phase, pour pouvoir expliquer chaque brique en entretien.

## Phase 0 — Setup du monorepo (2026-11-16)
**Ce qui a été construit :** l'arborescence du monorepo, deux projets Python (`pipeline`, `backend`)
gérés par uv avec ruff et pytest, Postgres 16 + pgvector via docker-compose (schémas `catalog`,
`app`, `mart`), un Makefile et trois workflows GitHub Actions (lint, tests, audit, base).

**Concepts clés :**
- **Lockfile (`uv.lock`)** : fige la version exacte de chaque dépendance, y compris les dépendances
  indirectes. Deux machines qui font `uv sync --locked` obtiennent exactement le même environnement :
  c'est la base de la reproductibilité.
- **pgvector** : extension Postgres qui ajoute un type `vector` et la recherche de plus proches
  voisins. Elle permet de stocker les embeddings dans la même base que le catalogue, sans base
  vectorielle séparée.
- **CI avec filtres de chemins** : chaque workflow ne tourne que si les fichiers qui le concernent
  changent. On garde un retour rapide et on n'use pas les minutes de CI gratuites.
- **Fail fast sur la config** : `load_settings` vérifie les sections obligatoires dès le chargement,
  au lieu de planter au milieu d'un job Spark long.

**Pourquoi ce choix :** voir [ADR 001](decisions/001-monorepo-et-outillage.md). En résumé : monorepo
pour la simplicité, environnements séparés pour éviter les conflits Airflow/FastAPI, uv pour la vitesse
et le lockfile, WSL2 parce que PySpark le demande.

**3 questions d'entretien possibles :**
1. *Pourquoi séparer `pipeline` et `backend` en deux environnements Python ?*
   Leurs dépendances ont des cycles de vie différents (Airflow fige beaucoup de versions), et l'image
   Docker de l'API doit rester légère, donc sans Spark.
2. *Pourquoi trois schémas Postgres ?*
   Ils séparent les responsabilités : référentiel (`catalog`), données personnelles (`app`, soumises
   au RGPD) et analytique (`mart`). On peut ensuite donner des droits différents à chacun, par
   exemple Power BI en lecture seule sur `mart`.
3. *Que vérifie ta CI ?*
   Le lint et le formatage (ruff), les tests (pytest), les failles connues des dépendances
   (pip-audit), les motifs de code dangereux (bandit), et le fait que la base démarre avec pgvector
   et ses schémas.
