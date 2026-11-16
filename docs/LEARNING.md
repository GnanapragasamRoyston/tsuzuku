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

## Phase 2 — Marts Spark → Postgres (2026-11-16)
**Ce qui a été construit :** `make spark` calcule avec Spark, sur 107 M interactions, la courbe de
drop de chaque anime, son épisode critique, son point de non-retour et la rétention par genre et
studio, puis charge ces marts et le catalogue anime dans Postgres (COPY, transactions, upsert).

**Concepts clés :**
- **Analyse de survie** : on suit des « individus » (spectateurs) jusqu'à un événement (le drop).
  Le *risque* à l'épisode *e* est la probabilité de lâcher pour quelqu'un qui a atteint *e*. Les
  spectateurs encore en cours sont *censurés à droite* : on ne connaît pas encore leur issue.
- **Biais de déclaration** : sur MAL, les gens marquent bien plus souvent « Completed » que
  « Dropped ». Un seuil absolu (« 90 % finissent ») était franchi dès l'épisode 1 partout ; une
  mesure *relative* (risque divisé par 4 par rapport au départ) compare l'anime à lui-même et
  neutralise ce biais. Leçon : un seuil choisi sur le papier se valide sur les données.
- **Agréger avant d'exploser** : on résume d'abord par anime (16 000 lignes), puis on éclate les
  genres. Une médiane, elle, ne s'additionne pas : elle exige les lignes individuelles
  (`percentile_approx`, approximation contrôlée).
- **COPY et transactions** : COPY envoie toutes les lignes en un flux (bien plus rapide que des
  INSERT). Le remplacement d'un mart (TRUNCATE + INSERT) tient dans une transaction : un lecteur
  voit l'ancienne ou la nouvelle version, jamais une table vide.
- **Upsert et ids stables** : `INSERT … ON CONFLICT DO UPDATE` met à jour une œuvre sans changer son
  `id`, auquel les listes des utilisateurs pointeront.
- **Verrous Postgres** : TRUNCATE attend la fin des lectures en cours. Une transaction de lecture
  restée ouverte a bloqué la suite de tests pendant 10 min ; d'où `lock_timeout` (échec clair après
  30 s) et des connexions de test en autocommit.

**Pourquoi ce choix :** voir [ADR 003](decisions/003-marts-drop-et-chargement-postgres.md). JDBC
Spark écarté (driver Java à télécharger, peu testable), `toPandas()` aussi (types numpy, dépendances
en plus) : `toLocalIterator()` + COPY suffit pour des marts de quelques centaines de milliers de
lignes. Kaplan-Meier complet gardé comme piste.

**3 questions d'entretien possibles :**
1. *Comment définis-tu l'épisode critique, et pourquoi exclure l'épisode 0 ?*
   C'est l'épisode ≥ 1 qui concentre le plus de drops, publié seulement avec assez de volume
   (≥ 50 drops, ≥ 3 épisodes). L'épisode 0, ce sont des gens qui n'ont jamais commencé : il
   gagnerait pour beaucoup d'animes sans rien dire du contenu. Il reste visible dans la courbe.
2. *Comment as-tu validé que tes indicateurs avaient du sens ?*
   Contrôles automatiques (chaque courbe finit à 1, taux dans [0, 1]) et contrôle à la main sur des
   séries connues : Death Note a son épisode critique au 25 et son point de non-retour au 26 ;
   Naruto au 135, au début des fillers. Et c'est en mesurant la distribution que j'ai vu que la
   première définition du point de non-retour ne discriminait rien.
3. *Pourquoi ne pas tout calculer en SQL dans Postgres ?*
   Postgres n'est pas fait pour scanner 107 M lignes à chaque calcul ; Spark parallélise sur tous
   les cœurs et lit du Parquet colonnaire. Postgres sert les *résultats* (quelques centaines de
   milliers de lignes) à l'API et à Power BI, avec index et contraintes.
