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

## Phase 1 — Données (2026-11-16)
**Ce qui a été construit :** `make data` télécharge les 5 CSV Kaggle (idempotent, sha256), les
convertit en Parquet typé avec PySpark (`staging`), filtre adulte/orphelins/statuts inconnus/doublons
(`clean`), produit `reports/data_quality.{json,md}` et un échantillon de dev par utilisateurs.

**Concepts clés :**
- **Parquet (format colonnaire)** : les valeurs d'une même colonne sont stockées ensemble et
  compressées. Lire 2 colonnes sur 5 ne lit que ces 2 colonnes, et le schéma voyage avec les
  données. Ici, 2,9 Go de CSV deviennent ~450 Mo par couche.
- **Couches staging / clean (architecture « médaillon »)** : staging = la source fidèle mais typée,
  clean = les données sur lesquelles on a appliqué les règles métier. Garder les deux permet de
  mesurer précisément ce que chaque règle retire, et de rejouer clean sans relire les CSV.
- **Broadcast join** : quand une table est petite (16 000 animes), Spark en envoie une copie à
  chaque tâche au lieu de redistribuer (« shuffle ») les 109 M lignes de l'autre table par clé.
  La jointure devient un simple filtre local.
- **Semi-jointure (`left_semi`)** : garde les lignes de gauche qui ont une correspondance à droite,
  sans ajouter de colonnes. Joindre sur la liste des ids *autorisés* exclut d'un coup les adultes
  et les orphelins.
- **Échantillonnage par hachage** : `xxhash64(user_id, seed)` décide utilisateur par utilisateur.
  Le résultat est reproductible quel que soit le partitionnement, on garde tout l'historique de
  chaque utilisateur tiré, et les deux tables d'interactions gardent les mêmes utilisateurs.
- **Idempotence par fraîcheur** : comme `make`, une étape est refaite si une sortie manque (pas de
  `_SUCCESS`) ou si elle est plus ancienne qu'une de ses entrées.

**Pourquoi ce choix :** voir [ADR 002](decisions/002-donnees-brutes-parquet.md). pandas est écarté
(109 M lignes), `inferSchema` aussi (une passe de plus, risque d'erreur de type), et `df.sample()`
parce qu'il tire des lignes et non des utilisateurs. Charger les données brutes dans Postgres
n'apporterait rien : seuls les marts agrégés y iront (phase 2).

**3 questions d'entretien possibles :**
1. *Comment tu t'assures que tes données sont propres ?*
   Un rapport qualité généré à chaque run : nulls, doublons, valeurs hors plage, codes de statut
   inconnus, incohérences (épisodes vus > épisodes de l'anime), et une ventilation exacte de ce que
   chaque filtre retire. Les tests vérifient que la somme des retraits égale l'écart de lignes.
   Exemple trouvé : des statuts 0, 5, 33 et 55 qui n'existent pas dans la table de référence.
2. *Pourquoi un schéma explicite plutôt que l'inférence ?*
   L'inférence relit tout le fichier (2 Go) juste pour deviner les types, et devine mal sur des
   colonnes qui mélangent nombres et « Unknown ». Avec un schéma explicite en mode PERMISSIVE, une
   valeur illisible devient null et elle est comptée, au lieu de faire planter le job ou de
   disparaître en silence.
3. *Pourquoi le filtre adulte se fait-il sur le rating ET sur le genre ?*
   Parce que les données le demandent : le rapport montre 3 animes classés Hentai sans rating Rx.
   Et les animes orphelins (absents du catalogue) sont exclus aussi, puisqu'on ne peut pas prouver
   qu'ils sont tout public.
