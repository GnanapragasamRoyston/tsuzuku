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

## Phase 3 — Modèle de drop (2026-11-16)
**Ce qui a été construit :** `make train` calcule avec Spark les features des 71 M lignes
Completed/Dropped, entraîne trois modèles scikit-learn sur 3 % des utilisateurs, puis écrit
`reports/drop_metrics.json`, quatre figures, une fiche modèle et un artefact archivé par run.

**Concepts clés :**
- **PR-AUC plutôt que ROC-AUC** : avec 5,91 % de drops, la ROC-AUC est flattée par la masse des
  négatifs faciles à classer. La PR-AUC ne regarde que la classe rare (précision et rappel) ; son
  plancher est le taux de positifs (0,056 sur le test), pas 0,5. C'est elle qui sert à choisir.
- **Split par groupe** : toutes les lignes d'un utilisateur vont dans un seul des trois lots
  (`GroupShuffleSplit`, 6 702 / 1 437 / 1 437 utilisateurs). Sinon le modèle reconnaît un profil
  déjà vu à l'entraînement et les métriques sont trop optimistes pour un nouvel utilisateur.
- **Leave-one-out et fuite de la cible** : le taux de drop d'un utilisateur est calculé sans la
  ligne qu'on prédit, sinon la réponse est dans la feature. Même logique pour les colonnes
  interdites (`watched_episodes`, note de la ligne, agrégats MAL) : un test bloque leur retour.
- **Training-serving skew** : les features sont codées deux fois, en Spark (entraînement) et en
  Python pur (API). Si les deux versions divergent, le modèle reçoit en production des valeurs
  qu'il n'a jamais vues. Un test de parité les compare valeur par valeur sur un même jeu.
- **Calibration et ECE** : un modèle est calibré si, parmi les cas notés « 30 % », environ 30 %
  lâchent vraiment. L'ECE est l'écart moyen entre probabilité prédite et taux observé, par
  déciles. Ici 0,0053 sans correction : la calibration isotonique n'a pas été activée.
- **Importance par permutation** : on mélange une colonne du test et on mesure la perte de PR-AUC.
  Elle dit *quelles* variables comptent, pas *dans quel sens*. Des variables corrélées (les parts
  de genre) se compensent : leur importance individuelle est sous-estimée.
- **Disque local de Spark** : sous WSL, `/tmp` est un tmpfs en RAM ; le job y a échoué (« No space
  left on device »). Correctif : `spark.local.dir` sur le disque, et jointure broadcast des totaux
  par utilisateur (≈ 320 000 lignes) au lieu d'un shuffle des 71 M lignes.
- **Tests isolés** : deux suites lancées en même temps sur la même base de test se bloquaient.
  Chaque exécution crée maintenant sa propre base jetable.

**Pourquoi ce choix :** voir [ADR 004](decisions/004-modele-de-drop.md). `class_weight="balanced"`
écarté : il gonfle les probabilités, or l'appli affiche un pourcentage. Split aléatoire par ligne
écarté (fuite par l'utilisateur). Calibration isotonique codée mais laissée inactive, l'ECE étant
déjà faible. Figure précision-rappel de la baseline : une droite horizontale au taux de positifs,
car la diagonale tracée d'abord était trompeuse. Piste non traitée : intervalles de confiance par
bootstrap par utilisateur sur la PR-AUC test.

**3 questions d'entretien possibles :**
1. *Ton modèle a une ROC-AUC de 0,90 : il est bon ?*
   Ce chiffre seul ne suffit pas avec 5,6 % de positifs sur le test. Je regarde la PR-AUC : 0,432
   pour le gradient boosting, contre 0,361 pour la régression logistique et 0,056 pour la baseline.
   Au seuil choisi sur la validation (0,241), la précision est de 0,395 et le rappel de 0,489 :
   8 587 drops détectés sur 17 552, pour 13 169 fausses alertes.
2. *Comment t'assures-tu qu'il n'y a pas de fuite de données ?*
   Trois garde-fous. Le split est fait par utilisateur. Les features utilisateur sont en
   leave-one-out. Une liste de colonnes interdites est testée automatiquement : par exemple, 54 %
   des drops ne sont pas notés contre 15 % des Completed, donc la note révèle presque l'issue.
   Le test n'est évalué qu'une fois ; hyperparamètres, modèle et seuil sont choisis sur la validation.
   Limite assumée : le dataset n'a pas de dates, donc pas de split temporel.
3. *Quelles variables comptent le plus, et que peux-tu en conclure ?*
   En perte de PR-AUC par permutation : le taux de drop historique de l'utilisateur (0,301), le
   nombre d'épisodes (0,215), le rang de popularité (0,124) et l'année (0,089). La suivante tombe à
   0,012. Je n'en conclus pas le sens de l'effet : la permutation mesure une importance, pas une
   direction, et elle sous-estime les variables corrélées entre elles.
