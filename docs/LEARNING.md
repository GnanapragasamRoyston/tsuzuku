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

## Phase 4 — Recommandation ALS (2026-11-17)
**Ce qui a été construit :** `make reco` filtre les notes avec Spark, compare une baseline de
popularité, un ALS explicite et un ALS implicite (Spark MLlib), évalue par fold-in NumPy des
utilisateurs jamais vus, puis exporte les facteurs des animes (Parquet + fiche JSON) pour l'API.

**Concepts clés :**
- **ALS et factorisation matricielle** : on résume chaque utilisateur et chaque anime par un
  vecteur de `rank` nombres (ici 128) ; le score d'un couple est leur produit scalaire. ALS
  (« moindres carrés alternés ») fixe les vecteurs des animes, résout ceux des utilisateurs, puis
  l'inverse, et recommence. Chaque demi-étape est un problème de moindres carrés avec une solution
  exacte, facile à paralléliser dans Spark.
- **Explicite vs implicite, et confiance** : en explicite, le modèle prédit la note et n'apprend
  que sur les notes observées. En implicite, il prédit « va-t-il aimer ? » (1 ou 0) sur **tout**
  le catalogue, et la note sert de *confiance* : ici note − 5, donc un 10 pèse plus qu'un 6, et
  une note sous 5 est un « non » dont on est sûr. Un anime non vu est un « non » peu sûr.
- **Fold-in / démarrage à froid** : un nouvel utilisateur n'a pas de vecteur. Mais à vecteurs
  d'animes fixés, le sien se calcule en résolvant un seul système linéaire (une demi-étape d'ALS
  pour lui seul), en NumPy, sans Spark. Un test de parité vérifie que ce calcul retrouve les
  vecteurs de Spark : les conventions (régularisation λ·n) sont faciles à rater en silence.
- **NDCG@K, précision@K, rappel@K, couverture** : précision@K = part des K recommandations qui
  sont aimées ; rappel@K = part des animes aimés retrouvés dans le top K ; NDCG@K fait pareil mais
  un bon titre en 1re place compte plus qu'en 10e. La couverture est la part du catalogue
  recommandée au moins une fois : la popularité ne couvre que 0,006 du catalogue à K = 10.
- **Split par utilisateur et masquage** : 80 % des utilisateurs entraînent l'ALS ; les autres ne
  sont jamais vus. Pour eux, on montre 80 % de leurs notes au fold-in et on cache 20 %, à
  retrouver. On mesure ainsi le vrai chemin de production. Sans dates, le masquage est aléatoire.
- **Une bonne RMSE ne fait pas un bon classement** : la RMSE ne juge que la note prédite sur des
  animes que l'utilisateur a *choisi* de voir. Recommander, c'est classer tout le catalogue,
  surtout des animes non vus. L'ALS explicite a une RMSE de 1,096 contre 1,503 pour la moyenne de
  l'anime, mais une NDCG@10 de 0,212 contre 0,193 pour la popularité : presque rien.
- **Filtre itératif** : retirer les animes peu notés peut faire passer un utilisateur sous son
  seuil, et inversement. On répète jusqu'à stabilité (3 passes ici).

**Pourquoi ce choix :** voir [ADR 005](decisions/005-recommandation-als.md). Split par note
écarté : l'ALS connaîtrait déjà l'utilisateur, ce qui n'arrive jamais dans l'appli. Sélection sur
la RMSE écartée : elle ne mesure pas la qualité d'une liste. Explicite ou implicite : on n'a pas
tranché sur le papier, on a comparé les deux sur la NDCG@10 de validation. Modèle Spark dans
l'API écarté (JVM dans l'image) : on exporte les facteurs en Parquet et on refait le fold-in en
NumPy. Grille sur tout le train écartée (40 entraînements) : 25 % des utilisateurs, puis
réentraînement des deux meilleurs. Limites assumées : meilleur `rank` (128) au bord de la grille,
pas d'intervalles de confiance.

**3 questions d'entretien possibles :**
1. *Pourquoi l'ALS implicite alors que tu as de vraies notes ?*
   Parce que je l'ai mesuré. Sur le test, NDCG@10 de 0,493 pour l'implicite, 0,212 pour
   l'explicite et 0,193 pour la popularité. L'explicite prédit bien les notes (RMSE 1,096 contre
   1,503 pour la moyenne de l'anime) mais n'apprend que sur ce que les gens ont choisi de voir.
   L'implicite utilise aussi le fait qu'un anime n'a pas été vu, et garde la note comme confiance.
2. *Comment recommandes-tu à un utilisateur qui vient de s'inscrire ?*
   Par fold-in : avec les vecteurs des 10 859 animes fixés, je calcule son vecteur par moindres
   carrés régularisés à partir de ses titres aimés (note par défaut 8), en NumPy dans l'API. Je
   l'ai évalué dans ce régime : avec 3 titres, l'ALS (0,175) fait moins bien que la popularité
   (0,193) ; avec 5 il passe devant (0,214), avec 10 il atteint 0,281. D'où la proposition : au
   moins 5 titres à l'onboarding, popularité en dessous.
3. *Comment sais-tu que ton évaluation n'est pas trop optimiste ?*
   Les 26 562 utilisateurs de test ne sont jamais vus par l'ALS : ils passent par le même fold-in
   que la production. Les hyperparamètres et le choix du modèle se font sur la validation, le test
   est évalué une seule fois. Limites que j'assume : pas de dates, donc masquage aléatoire ; et
   le meilleur rank (128) est au bord de la grille, donc l'optimum n'est pas encadré.

## Phase 5 — API data (2026-11-20)
**Ce qui a été construit :** une API FastAPI (catalogue, saison en cours via Jikan, recos ALS,
risque de drop) en mode démo, un paquet `packages/tsuzuku-ml` partagé avec le pipeline, et une
image Docker multi-étapes lancée par `make api-up`, testée en CI sans base ni modèles.

**Concepts clés :**
- **Training-serving skew et code partagé** : si l'API calcule les features ou le fold-in
  autrement qu'à l'entraînement, le modèle répond faux sans erreur. Le pipeline et l'API importent
  donc le même paquet (`tsuzuku_ml`), sans copie. Au démarrage, l'API rejoue le `parity_check` de
  la fiche (mêmes notes → même top 10) ; les infos d'anime servies ont été comparées à celles de
  l'entraînement : 0 différence sur 16 214 animes.
- **Lifespan et dégradation contrôlée** : le `lifespan` de FastAPI charge les modèles une fois au
  démarrage. Un modèle absent ne fait pas planter l'API : ses routes répondent 503 (« indisponible,
  réessaie plus tard ») et pas 500 (« bug »). `/health` (vivacité : le processus tourne-t-il ?)
  répond toujours 200 ; `/health/ready` (disponibilité : peut-on lui envoyer du trafic ?) répond
  503 s'il manque la base ou un modèle.
- **Dépendance FastAPI (`Depends`)** : une route déclare ce dont elle a besoin (session de base,
  modèle, règles) et FastAPI le fournit à chaque requête. Le code de la route reste simple, la
  session est fermée automatiquement, et les tests remplacent facilement une dépendance.
- **Cache, retries, backoff et circuit simple** : Jikan est une API externe lente ou en panne par
  moments. Timeout de 5 s, 2 retries avec attente croissante (ou `Retry-After`), cache d'une heure,
  dernière réponse servie en « stale » si Jikan tombe. Après un échec, on ne réessaie pas pendant
  120 s : c'est un disjoncteur (« circuit breaker ») simplifié.
- **Mode démo** : pas de comptes avant la phase 7, donc le profil (titres aimés, liste) est envoyé
  dans la requête. Les services sont écrits pour recevoir une liste, d'où qu'elle vienne : les
  routes `/me/...` réutiliseront les mêmes avec la liste lue en base.
- **Image Docker multi-étapes et liste blanche** : une étape construit le venv avec uv, l'image
  finale ne garde que lui (pas d'outils de build, utilisateur non-root). Le contexte de build est la
  racine du dépôt, qui contient `data/` (plusieurs Go) : le `.dockerignore` exclut tout (`*`) puis
  n'autorise que le nécessaire.

**Pourquoi ce choix :** voir [ADR 006](decisions/006-api-data.md). Copie de `fold_in.py` dans le
backend (prévue par l'ADR 005) écartée : deux copies finissent par diverger ; un paquet partagé
sans Spark garde PySpark hors de l'image. SQLAlchemy asynchrone écarté : plus complexe, sans gain
mesurable ici, et les calculs NumPy restent synchrones. Jikan sans cache écarté : panne et limites
de débit. Chiffre de drop pour un anime récent écarté : ses features seraient vides, le chiffre
serait inventé. Limites assumées : Jikan injoignable pendant toute la phase (testé avec un Jikan
simulé), image de 1,02 GB, `parity_check` strict qui pourrait désactiver la reco si un calcul
flottant diffère entre machines.

**3 questions d'entretien possibles :**
1. *Comment garantis-tu que l'API calcule la même chose que ton entraînement ?*
   Le pipeline et l'API importent le même paquet Python, sans copie. Au démarrage, l'API rejoue un
   cas de référence enregistré dans la fiche du modèle et refuse le modèle si le top 10 diffère. J'ai
   aussi comparé les infos d'anime servies par l'API à celles de l'entraînement : 16 214 animes,
   9 colonnes, 0 différence. Enfin, un anime que le modèle n'a jamais vu reçoit
   « insufficient_data », pas un chiffre.
2. *Pourquoi servir la popularité à un utilisateur qui a donné moins de 5 titres ?*
   Parce que je l'ai mesuré en phase 4 : avec 3 titres aimés, l'ALS implicite a une NDCG@10 de
   0,175 contre 0,193 pour la popularité ; avec 5, il passe devant (0,214). Seuls les titres
   aimés (note ≥ 8) comptent, car c'est ce qui a été évalué. La réponse indique la stratégie et la
   raison, pour que le front puisse l'expliquer.
3. *Que se passe-t-il si Jikan tombe ?*
   S'il y a une réponse en cache, l'API la sert marquée « stale ». Sinon, elle répond 503. J'ai
   mesuré le pire cas : 47,2 s avant le 503 avec un timeout de 10 s et 3 retries, d'où le passage
   à 5 s et 2 retries (18,2 s). Ensuite, pendant 120 s, elle ne réessaie pas et répond tout de
   suite : une panne de Jikan ne bloque pas le reste de l'API.

## Phase 6 — Airflow : ingestion Jikan et AniList (2026-11-20)
**Ce qui a été construit :** deux DAG Airflow 2.11 dans docker-compose : `jikan_daily_ingest`
(stats quotidiennes de la saison) et `anilist_catalog_sync` (5 000 mangas, manhwas et manhuas
chaque lundi), une image Airflow sans PySpark testée en CI, et `/trending` qui lit la base.

**Concepts clés :**
- **DAG et tâches** : un DAG (graphe orienté sans cycle) décrit des tâches et leur ordre ; le
  scheduler d'Airflow les lance selon un planning, les réessaie en cas d'échec et garde
  l'historique de chaque exécution. Mes DAG sont minces : ils enchaînent des fonctions Python
  testées sans Airflow.
- **Idempotence et upsert** : une opération est idempotente si la rejouer donne le même résultat.
  Un upsert (`INSERT … ON CONFLICT … DO UPDATE`) insère la ligne si sa clé est nouvelle, sinon la
  met à jour. Clé (date, œuvre) pour les stats, `anilist_id` pour le catalogue : relancer un DAG
  ne crée aucun doublon.
- **Atterrissage brut et relance d'une tâche** : chaque tâche écrit sa sortie dans un fichier daté
  (`data/raw/<source>/<date>/`) que la suivante relit. Si `load` échoue, je relance `load` seul :
  pas besoin de rappeler l'API. L'écriture est atomique (fichier temporaire puis renommage) : on ne
  lit jamais un fichier à moitié écrit.
- **Date logique et timetable** : chaque run d'Airflow a une date logique, qui sert à nommer ses
  fichiers et ses lignes. Avec le cron « classique » d'Airflow 2, c'est le début de l'intervalle :
  un run manuel est daté de la veille. Avec `CronTriggerTimetable`, c'est l'heure de déclenchement :
  un run est daté du jour où il tourne.
- **Respect des limites de débit** : un client commun espace les appels (1 s pour Jikan, 2,1 s pour
  AniList), réessaie sur 429, 5xx et erreurs réseau avec une attente qui double (backoff
  exponentiel), suit `Retry-After` si l'API le donne, et attend la remise à zéro quand
  `X-RateLimit-Remaining` tombe à 0, avant de provoquer un 429.
- **Contrôle qualité et « échec isolé »** : la dernière tâche vérifie en base (lignes présentes,
  pas de compteur négatif, pas de contenu adulte, tous les titres gardés chargés) et écrit un
  rapport JSON ; si un contrôle échoue, la tâche échoue. Un anime dont les stats échouent garde
  une ligne avec score et membres ; au-delà de 20 % d'échecs, ce n'est plus isolé : la tâche
  s'arrête.
- **Image sans PySpark et contraintes de dépendances** : l'image Airflow installe le pipeline avec
  `--no-deps` et seulement httpx, psycopg et pyyaml, pour éviter PySpark et une JVM. Le fichier de
  contraintes d'Airflow fige les versions compatibles. Un test vérifie qu'aucun module d'ingestion
  n'importe PySpark : il a trouvé une importation indirecte, corrigée.

**Pourquoi ce choix :** voir [ADR 007](decisions/007-airflow-ingestion.md). CeleryExecutor + Redis
écarté : inutile pour deux DAG linéaires sur une machine ; LocalExecutor suffit. Transport des
données par XCom écarté : XCom est fait pour de petits messages, et les fichiers bruts permettent
de rejouer une tâche. Supprimer les titres sortis du top écarté : les listes des utilisateurs
pointeront dessus, on remet seulement leur rang à NULL. Rattrapage (`catchup`) écarté : Jikan ne
donne que l'état actuel. AniList comme repli pour les stats d'anime écarté : autre population que
MAL, séries incomparables. Limites assumées : Jikan en panne pendant toute la phase (DAG testé avec
des réponses simulées, 1re exécution réelle à refaire), embeddings des nouvelles œuvres en
phase 10, même utilisateur Postgres pour Airflow et Tsuzuku en dev.

**3 questions d'entretien possibles :**
1. *Comment sais-tu que ton DAG est idempotent ?*
   Les chargements sont des upserts sur une clé naturelle : (date, œuvre) pour les stats,
   `anilist_id` pour le catalogue, dans une transaction. Des tests rejouent la même date et
   vérifient le nombre de lignes. Et je l'ai vu sur les vraies données : la relance AniList sur le
   même intervalle a donné 0 insertion et 5 000 mises à jour (`reports/exploration_2026-11-20.json`,
   `anilist_first_runs`).
2. *Pourquoi as-tu changé de timetable ?*
   Avec le cron classique, la date logique est le début de l'intervalle. Mes deux premiers runs
   AniList, lancés le 2026-11-20, ont été datés du 2026-11-16. Pour Jikan, c'est grave : il ne
   donne que l'état actuel, donc un run manuel aurait rangé les chiffres du jour sous la date de la
   veille et écrasé son snapshot. Avec `CronTriggerTimetable`, la date est l'heure de déclenchement,
   et le code refuse en plus de collecter Jikan pour une date passée.
3. *Comment respectes-tu les limites d'une API publique ?*
   J'ai lu la limite d'AniList dans ses en-têtes : 30 requêtes par minute. J'espace donc les appels
   de 2,1 s ; Jikan, limité à 3 par seconde et 60 par minute, est appelé une fois par seconde
   (`config/settings.yaml`). Le client réessaie sur 429 et 5xx avec une attente croissante, suit
   `Retry-After` et attend la remise à zéro du quota annoncée par `X-RateLimit-Reset`. Les 100 pages
   AniList ont pris 3,5 minutes à la 1re exécution, contrôles qualité au vert.

## Phase 7 — Comptes et listes (2026-11-21)
**Ce qui a été construit :** inscription, connexion et déconnexion (argon2id, JWT en cookie
`httpOnly`), ma liste (`/me/list`), onboarding, recos et risque de drop calculés depuis la base,
export et suppression RGPD, migrations Alembic du schéma `app`, limitation de débit.

**Concepts clés :**
- **Hachage de mot de passe (argon2id)** : on ne stocke jamais le mot de passe, seulement une
  empreinte lente à calculer et salée (un aléa différent par compte). Même avec la base volée,
  tester des milliards de mots de passe coûte trop cher, et deux comptes au même mot de passe
  ont des empreintes différentes.
- **JWT et cookie `httpOnly`** : un JWT est un petit jeton signé (ici : id du compte, version,
  expiration). Le serveur vérifie la signature sans rien stocker. Dans un cookie `httpOnly`, le
  JavaScript de la page ne peut pas le lire : un script injecté ne peut pas le voler. `Secure` :
  envoyé seulement en HTTPS. `SameSite=Lax` : pas envoyé avec un POST venant d'un autre site.
- **Révocation par `token_version`** : un JWT reste valide jusqu'à son expiration. Pour qu'une
  déconnexion l'invalide vraiment, il porte la version du compte ; la déconnexion l'incrémente
  et tous les jetons émis avant sont refusés.
- **CSRF** : une attaque où un autre site fait envoyer une requête par ton navigateur, avec ton
  cookie. `SameSite=Lax`, CORS limité à l'origine du front et des corps JSON la bloquent.
- **Énumération de comptes** : si « email inconnu » et « mauvais mot de passe » répondent
  différemment (message ou durée), un attaquant apprend qui est inscrit. Même message, et une
  vérification argon2 factice quand l'email n'existe pas, pour la même durée.
- **Migrations Alembic** : chaque changement de schéma est un script versionné, appliqué dans
  l'ordre (`upgrade`) et réversible (`downgrade`). Un test vérifie que les modèles SQLAlchemy et
  les migrations décrivent la même chose.
- **IDOR et isolation** : chaque requête de liste filtre sur l'id du jeton, jamais sur un id
  envoyé par le client. Des tests vérifient qu'un compte ne lit ni ne modifie la liste d'un autre.

**Pourquoi ce choix :** voir [ADR 008](decisions/008-comptes-et-listes.md). Jeton dans
`localStorage` écarté : lisible par n'importe quel script de la page. Table de sessions écartée :
une lecture de plus par requête pour un besoin couvert par `token_version`. Alembic sur tout le
schéma écarté : `catalog` et `mart` sont rechargés par le pipeline, deux propriétaires pour une
table, c'est deux façons de la casser. Règles de composition des mots de passe écartées au profit
de la longueur (NIST). Limites assumées : limitation de débit en mémoire (une seule instance, à
revoir en phase 11), déconnexion qui ferme toutes les sessions du compte.

**3 questions d'entretien possibles :**
1. *Pourquoi un cookie `httpOnly` plutôt que le `localStorage` ?*
   Tout script exécuté dans la page lit le `localStorage` : une faille XSS suffit à voler la
   session. Un cookie `httpOnly` est envoyé par le navigateur mais invisible du JavaScript. Le
   prix est le risque CSRF, couvert par `SameSite=Lax` et un CORS restreint.
2. *Comment invalides-tu un JWT à la déconnexion, alors qu'il est sans état ?*
   Le jeton contient la `token_version` du compte. À chaque requête, je compare avec la valeur en
   base (une lecture par clé primaire, que je fais déjà pour charger le compte). La déconnexion
   incrémente la version : tous les anciens jetons sont refusés. Un test copie un jeton avant la
   déconnexion et vérifie qu'il ne marche plus.
3. *Comment gères-tu la conformité RGPD ?*
   Export JSON de toutes les données fournies (profil, liste, critiques, onboarding), sans les
   données de sécurité. Suppression du compte avec mot de passe redemandé, et cascade en base :
   un test vérifie qu'il ne reste aucune ligne. Aucun email ni mot de passe dans les journaux
   (testé), pas de traceur tiers, et une page de confidentialité (`docs/privacy.md`).

## Phase 8 — Front, partie 1 : accueil, comptes, onboarding, ma liste (2026-11-21)
**Ce qui a été construit :** un front Next.js 16 au design « Journal de bord » (DESIGN.md) :
accueil rendu côté serveur, inscription et connexion, onboarding de 10 œuvres, « Ma liste » avec
« +1 ép. » et « J'ai lâché », recos « Pour toi » ; couvertures récupérées sur AniList ; tests
Vitest, Playwright et axe-core.

**Concepts clés :**
- **Design tokens** : les couleurs, tailles, espacements et rayons sont des variables nommées
  (`bg`, `accent`, `spacing-4`…) déclarées une seule fois. Les valeurs par défaut de Tailwind
  sont supprimées et un test refuse toute valeur en dur : le code ne peut pas s'écarter du
  design, et un contraste insuffisant casse la CI.
- **Contraste WCAG** : rapport de luminance entre texte et fond (4,5:1 pour le texte, 3:1 pour
  les éléments d'interface). Je le calcule par script plutôt que de l'estimer à l'œil ; axe-core
  le revérifie sur les pages réelles pendant les tests de bout en bout.
- **Relais d'API (rewrites)** : le navigateur appelle `/api/...` sur le front, qui transmet à
  FastAPI. Même origine : le cookie `httpOnly` part tout seul, pas de CORS, et le JavaScript ne
  voit jamais le jeton de session.
- **Server et Client Components** : l'accueil est rendu sur le serveur (rapide, sans
  JavaScript à exécuter pour l'afficher) ; les pages de compte tournent dans le navigateur avec
  TanStack Query, qui met en cache et met à jour les données après une action.
- **Suspense et streaming** : chaque section de l'accueil charge ses données dans sa propre
  limite `<Suspense>`. La page s'affiche tout de suite ; une API lente ne bloque que sa section.
- **Tests de bout en bout en build de production** : Playwright pilote un vrai navigateur sur
  la vraie API et une base dédiée. Ils ont trouvé un bug invisible en développement : le
  préchargement des liens avait mis en cache une redirection de visiteur.

**Pourquoi ce choix :** voir [ADR 009](decisions/009-front-next.md) et
[DESIGN.md](DESIGN.md). Appels directs du navigateur vers l'API écartés : CORS avec cookies, et
cookie tiers bloqué quand front et API sont sur deux domaines. Direction « Fiche technique »
(monospace, tableaux) écartée au profit du « Journal de bord » : plus proche d'un journal de fan.
TDD gardé pour la logique (progression, erreurs, formats) et non pour l'apparence des
composants, vérifiée par axe-core et des captures à 375 et 1440 px. Limite connue : derrière le
relais, l'API ne voit pas l'IP réelle des visiteurs ; la production devra passer par une
plateforme qui pose `X-Forwarded-For` (phase 11).

**3 questions d'entretien possibles :**
1. *Comment garantis-tu que le code respecte la charte graphique ?*
   Les tokens de DESIGN.md sont la seule palette disponible : les valeurs par défaut de Tailwind
   sont supprimées, donc `bg-red-500` ne génère rien. Un test refuse toute couleur hexadécimale,
   police ou valeur arbitraire dans le code, vérifie que chaque pas d'espacement existe, et
   recalcule les contrastes à partir du fichier de tokens. Il a bloqué deux écarts pendant la
   phase, que j'ai réglés en complétant DESIGN.md plutôt qu'en contournant le test.
2. *Pourquoi un relais `/api` plutôt qu'appeler l'API directement ?*
   Le cookie de session est `httpOnly` et `SameSite=Lax`. Si le navigateur appelait l'API sur
   un autre domaine, il faudrait ouvrir CORS avec cookies, et les navigateurs bloquent de plus en
   plus les cookies tiers. Avec le relais, tout est même origine. Le prix : l'API ne voit plus
   l'IP du visiteur, sauf si la plateforme réécrit `X-Forwarded-For` ; je l'ai mesuré et
   documenté.
3. *Qu'est-ce que tes tests de bout en bout ont trouvé ?*
   Après l'inscription, « Ma liste » renvoyait vers la connexion, alors que la session était
   valide. En build de production, Next précharge les liens visibles : il avait préchargé « Ma
   liste » quand j'étais visiteur, donc gardé la redirection en cache. Invisible en
   développement, où il n'y a pas de préchargement. Correctif : pas de préchargement des pages de
   compte et rafraîchissement du routeur à chaque changement de session.

## Phase 9 — Front, partie 2 : fiche œuvre, Pour toi, profil public (2026-11-22)
**Ce qui a été construit :** la fiche œuvre (risque de drop personnel, courbe de drop par épisode
avec épisode critique et point de non-retour, note sur 10), la page « Pour toi », et un profil
public opt-in (`/users/{pseudo}`, migration `profile_public`, `PATCH /me`).

**Concepts clés :**
- *Îlots client (islands)* : la page est rendue sur le serveur (catalogue public, rapide, sans
  JavaScript inutile) ; seules les parties qui dépendent du compte (ajout, note, risque) tournent
  dans le navigateur. On paie le JavaScript là où il sert.
- *Opt-in et minimisation (RGPD)* : une donnée personnelle n'est exposée que si la personne le
  choisit. Le profil est privé par défaut ; le rendre public est un geste explicite et réversible.
- *Énumération de comptes* : si « profil privé » et « pseudo inconnu » répondaient différemment,
  on pourrait tester l'existence d'un compte. Une seule réponse (404) ferme cette fuite.
- *Mise à jour optimiste* : l'interface applique le changement tout de suite et revient en arrière
  si le serveur refuse. Une case qui attend le réseau pour se cocher paraît cassée.

**Pourquoi ce choix :** courbe en CSS plutôt qu'une bibliothèque de graphes (une rangée de barres
ne justifie pas des dizaines de Ko de JavaScript, et la logique reste testable seule). Profil
public par défaut écarté (exposition sans consentement). Avatar écarté (l'upload d'images ouvre
une surface d'attaque et demande du stockage). Voir [ADR 011](decisions/011-front-partie-2.md).

**3 questions d'entretien possibles :**
1. *Pourquoi la même 404 pour un profil privé et un pseudo inconnu ?* — Sinon on peut savoir si un
   compte existe en essayant des pseudos (énumération). La réponse identique ne révèle rien.
2. *Comment rendre une courbe accessible ?* — Un résumé textuel (`role="img"` + `aria-label` : pic
   et repères), un tableau équivalent masqué visuellement, et jamais la couleur seule : chaque
   repère a aussi un libellé écrit.
3. *Pourquoi rendre la fiche côté serveur et le risque côté client ?* — Le catalogue est public et
   identique pour tous : le serveur le rend vite. Le risque dépend de la liste du compte, donc du
   cookie : il est calculé par l'API pour la personne connectée, dans un îlot client.

## Lot « qualité des jaquettes » et titres (2026-11-22)
**Ce qui a été construit :** jaquettes AniList deux fois plus grandes (460 px), image par défaut
écartée, titre anglais affiché d'abord, jaquette de secours composée sur une palette dédiée,
rapport de couverture, et « Proposer une jaquette » avec modération en ligne de commande.

**Concepts clés :**
- *Mesurer avant de construire* : la demande visait les manhwas « mal couverts » ; la mesure a
  montré 100 % de couverture sur le catalogue et un vrai manque ailleurs (animes, taille des
  images). Le chantier a été recentré sur ce qui changeait vraiment l'appli.
- *SSRF (Server-Side Request Forgery)* : si le serveur téléchargeait une URL donnée par un
  utilisateur, on pourrait lui faire appeler des adresses internes. Ici l'API ne télécharge
  jamais l'URL : elle la vérifie (liste exacte d'hôtes et de chemins) et la stocke.
- *Modération humaine* : une donnée venant d'un utilisateur n'est publiée qu'après validation ;
  une synchro automatique ne doit jamais défaire cette décision (`cover_source = 'suggestion'`).
- *Contraintes de design testées* : une couleur externe (AniList) n'est pas affichée brute ; elle
  est ramenée à une palette dont les contrastes sont vérifiés par un test.

**Pourquoi ce choix :** MangaUpdates mis de côté (sans élargir le catalogue, il ne remplissait
rien). Pas d'URL d'image devinée : chaque grande image est redemandée à AniList. Pas d'envoi de
fichiers ni de page d'administration (surface d'attaque). Voir
[ADR 012](decisions/012-qualite-des-jaquettes.md).

**3 questions d'entretien possibles :**
1. *Comment accepter une URL d'image d'un utilisateur sans risque ?* — Liste exacte d'hôtes et
   de chemins, HTTPS seulement, ni identifiants, ni port, ni paramètres ; on ne la télécharge
   pas côté serveur (pas de SSRF) et rien ne s'affiche avant validation humaine.
2. *Pourquoi ne pas afficher la couleur dominante fournie par AniList ?* — Elle est arbitraire :
   elle casserait les contrastes (accessibilité) et l'identité visuelle. On la ramène au ton le
   plus proche d'une palette dont les contrastes sont testés.
3. *Comment changer une règle de données sans relancer tout le pipeline ?* — Une mise à jour SQL
   unique, dans une transaction, qui applique exactement la nouvelle règle du code ; la prochaine
   exécution complète produit le même résultat.

## Phase 10 — Recos par le contenu : embeddings et pgvector (2026-11-22)
**Ce qui a été construit :** embeddings e5-small des 21 218 œuvres dans pgvector, recos mangas,
manhwas et manhuas par le contenu (hybride avec la popularité) avec raison cross-média, et
« Dans le même esprit » sur la fiche. Évalué avec le protocole de la phase 4.

**Concepts clés :**
- *Embedding* : un texte devient un vecteur ; deux œuvres proches par leur histoire ont des
  vecteurs proches (cosinus). On compare ainsi un anime et un manhwa sans aucune note commune.
- *Démarrage à froid côté objet* : sans interactions, l'ALS ne sait rien d'une œuvre ; le contenu,
  lui, la décrit dès son arrivée dans le catalogue.
- *Biais de popularité* : les œuvres que les gens aiment sont surtout connues. Une méthode qui
  l'ignore recommande des œuvres proches mais obscures et perd en NDCG ; on ajoute un a priori
  de popularité dont le poids est réglé sur la validation.
- *Réglage sans fuite* : β choisi sur des utilisateurs de validation, test mesuré une fois.

**Pourquoi ce choix :** e5-small plutôt que MiniLM (NDCG 4× meilleur, mesuré). Recherche exacte
plutôt qu'un index HNSW (21 000 vecteurs ; un index approximatif perd des résultats quand on
filtre). PyTorch hors Airflow et hors API (images légères ; l'API ne fait que des requêtes
pgvector). Voir [ADR 013](decisions/013-recos-par-le-contenu.md).

**3 questions d'entretien possibles :**
1. *Ton modèle de contenu bat-il la popularité ?* — Non sur ce protocole (0,182 contre 0,193) :
   le contenu seul (0,027) recommande l'obscur ; l'hybride s'approche de la popularité. Il sert
   là où il n'y a pas d'alternative (mangas, manhwas sans historique) et pour le cross-média.
2. *Comment as-tu choisi β ?* — Grille sur 5 000 utilisateurs de validation, règle du coude
   (plus petit β à 1 % du meilleur), test mesuré une seule fois. J'ai aussi constaté que la
   couverture n'augmentait pas au coude : je l'ai documenté plutôt que de le cacher.
3. *Pourquoi pas d'index ANN dans pgvector ?* — À 21 000 vecteurs la recherche exacte prend
   22 ms sur tout le catalogue et 4 ms pour les manhwas (mesuré, EXPLAIN ANALYZE), et HNSW filtré par type et par « déjà vu » peut renvoyer moins de
   résultats que demandé.

## Phase 11 — Déploiement : Vercel, Cloud Run, Neon (2026-11-24)
**Ce qui a été construit :** Tsuzuku en ligne (tsuzuku-eight.vercel.app) : front Vercel, API et
ingestion planifiée sur Cloud Run, base Neon avec pgvector, modèles sur Cloud Storage. Déploiement
automatique après une CI verte, sans clé, avec migration avant l'API et test de fumée.

**Concepts clés :**
- *Workload Identity Federation* : GitHub prouve son identité à Google avec un jeton OIDC de courte
  durée ; aucune clé de compte de service n'est stockée, et seul ce dépôt peut déployer.
- *Relais de confiance* : l'API est publique, mais n'accepte que les requêtes portant le secret
  du front ; elle ne croit l'IP du visiteur que si ce secret est valide. Un en-tête
  `X-Forwarded-For` venu d'un client ne se croit jamais.
- *Ordre de déploiement* : la base doit être migrée AVANT que la nouvelle API la lise ; un job de
  migration dédié passe en premier, sinon l'API répondrait 500 pendant la fenêtre de mise à jour.
- *Scale to zero* : 0 instance au repos = 0 € de calcul, au prix d'un démarrage à froid (2,9 à
  3,5 s mesurés pour l'application, ~5 s au premier chargement).

**Pourquoi ce choix :** Cloud Run (conteneur existant, gratuit au repos) plutôt qu'une VM ; Cloud
Run Jobs + Scheduler plutôt qu'Airflow en production (une VM permanente coûterait) ; Neon pour
pgvector gratuit ; clé JSON écartée au profit de Workload Identity. Voir
[ADR 014](decisions/014-deploiement.md).

**3 questions d'entretien possibles :**
1. *Comment ton CI/CD déploie-t-il sans clé ?* — Workload Identity Federation : GitHub Actions
   échange son jeton OIDC contre un jeton Google de courte durée, limité à ce dépôt et à un compte
   de service qui ne peut que déployer.
2. *Comment évites-tu qu'on contourne ta limite de connexion en changeant d'IP ?* — L'API ignore
   `X-Forwarded-For` ; l'IP vient d'un en-tête posé par le front, cru seulement avec un secret
   partagé ; vérifié en production (429 au 6e échec, aucune IP manquante).
3. *Que se passe-t-il si une migration casse ?* — Le job de migration tourne avant l'API ; s'il
   échoue, le déploiement s'arrête et l'ancienne version reste en ligne.

## Phase 12 — PWA : installable et hors ligne (2026-11-24)
**Ce qui a été construit :** service worker (Serwist, compatible Turbopack), règles de cache
testées, « Ma liste » lisible hors ligne avec bandeau et actions désactivées, invitation à
installer (Android et iPhone), pages `/installer` et `/hors-ligne`, icône « maskable ».

**Concepts clés :**
- *Service worker* : un script que le navigateur place entre la page et le réseau ; il décide,
  requête par requête, de répondre depuis un cache ou depuis le réseau.
- *Stratégies* : cache d'abord (fichiers qui ne changent pas), réseau d'abord (données qui doivent
  être fraîches), cache puis rafraîchi (catalogue : rapide, mis à jour en arrière-plan).
- *Données privées hors ligne* : un cache à part, vidé à la déconnexion et quand la session est
  refusée, pour qu'un téléphone partagé ne montre jamais la liste de quelqu'un d'autre.

**Pourquoi ce choix :** PWA plutôt que stores (ADR 010) ; Serwist plutôt qu'un service worker écrit
à la main ; réseau d'abord pour « Ma liste » (une session révoquée ne doit plus rien afficher).
Voir [ADR 015](decisions/015-pwa.md).

**3 questions d'entretien possibles :**
1. *Pourquoi pas « cache puis rafraîchi » pour la liste de l'utilisateur ?* — La réponse en cache
   s'afficherait même si la session a expiré : on prend le réseau d'abord et le cache seulement
   hors ligne.
2. *Comment tester un mode hors ligne ?* — Playwright coupe le réseau (`setOffline`), recharge, et
   vérifie la liste, le bandeau et la page de secours.
3. *Pourquoi ne pas proposer l'installation dès l'arrivée ?* — Une invite avant toute valeur perçue
   est refusée par réflexe ; on attend une action utile et on respecte « Plus tard ».
