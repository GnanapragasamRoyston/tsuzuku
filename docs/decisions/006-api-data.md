# ADR 006 — API data : code ML partagé, règle des 5 titres, dégradation contrôlée, Docker

**Date** : 2026-11-20 · **Statut** : accepté (choix validés par Royston)

## Contexte
La phase 5 expose les données et les modèles par une API FastAPI : catalogue (recherche, fiche
d'une œuvre avec ses indicateurs de drop), saison en cours (Jikan), recommandations (ALS de la
phase 4) et risque de drop (modèle de la phase 3).

Il n'y a pas encore de comptes (phase 7). L'API fonctionne en **mode démo** : le profil de
l'utilisateur (titres aimés, liste) est passé **dans la requête**. Les futures routes `/me/...`
appelleront les mêmes services avec la liste lue en base.

Contrainte centrale : l'API doit faire **exactement les mêmes calculs qu'à l'entraînement**.
Un modèle servi avec des features calculées autrement donne des prédictions fausses, sans aucune
erreur visible (« training-serving skew »).

## Décisions

### a) Un paquet partagé `packages/tsuzuku-ml` — option A, validée par Royston le 2026-11-20
Le code ML utilisé à la fois par le pipeline et par l'API vit dans un seul paquet Python :
- `fold_in.py` : vecteur d'un nouvel utilisateur (fold-in ALS), règle de classement
  `top_k_positions`, notes d'onboarding ;
- `drop_features.py` : le **contrat des colonnes** du modèle de drop (`feature_columns`, colonnes
  interdites), le calcul des features d'un utilisateur en Python pur (`feature_row`) et la mise en
  forme de la matrice d'entrée (`prepare_x`) ;
- `artifacts.py` : chargement et vérification des modèles. Contrôles : **sha256** de l'artefact
  comparé à celui de la fiche, **même version mineure de scikit-learn** qu'à l'entraînement pour
  le pickle de drop, **`schema_version`** pour la reco, forme et valeurs des facteurs, et
  **`parity_check`** rejoué au démarrage de l'API (mêmes notes → exactement le même top 10).

Le paquet est une **dépendance locale uv** (`path`, mode éditable) dans `pipeline/pyproject.toml`
et `backend/pyproject.toml`. Une modification est vue tout de suite des deux côtés.

Le paquet ne dépend **pas de Spark** (NumPy, pandas, pyarrow, joblib, scikit-learn) : l'image de
l'API ne contient pas PySpark. La version Spark des features de drop reste dans le pipeline ; son
test de parité avec `feature_row` reste côté pipeline (il a besoin de Spark).

**Ceci modifie l'ADR 005.** L'ADR 005 prévoyait que le backend garde une **copie vérifiée** de
`fold_in.py`. Il n'y a plus de copie : le pipeline et l'API importent le même fichier. Le
`parity_check` est conservé comme garde-fou au démarrage.

### b) Règle des 5 titres — validée par Royston le 2026-11-20
Sous `min_liked_for_als` = 5 animes **aimés** connus du modèle (`config/settings.yaml`, section
`api`), l'API sert la **popularité** au lieu de l'ALS.
- **Aimé** = note ≥ `relevant_min_score` de la fiche du modèle de reco, soit **8**
  (`models/reco_model.json`). C'est le seuil de pertinence mesuré en phase 4.
- Un choix d'onboarding **sans note** vaut la note par défaut, **8** (`onboarding_default_score`
  de la fiche) : il compte donc comme aimé.
- **Connu du modèle** = l'anime a un vecteur ALS. Un manga, un titre inconnu ou un anime absent
  du modèle (trop peu noté, ou postérieur à 2020) est renvoyé dans `liked_ignored`.
- La réponse dit toujours ce qui a été fait : `strategy` (`als` ou `popularity`) et `reason`
  (phrase lisible, par exemple « 3 anime(s) aimé(s) reconnu(s) : il en faut au moins 5 »).

Justification chiffrée (`reports/reco_metrics.json`, clé `onboarding_test`, NDCG@10 sur le test) :

| Animes aimés donnés | Popularité | ALS implicite |
|---|---|---|
| 3 | 0,193 | 0,175 |
| 5 | 0,193 | 0,214 |

Avec 3 titres, l'ALS fait moins bien que la popularité. Avec 5, il passe devant. Le seuil est
donc mis à 5.

Les titres **mal notés** (note < 8) sont quand même transmis au fold-in : en ALS implicite, une
note sous le neutre est une préférence négative (« vu, pas aimé »), c'est une information utile.
Mais ils **ne comptent pas dans les 5** : l'évaluation de la phase 4 ne donnait que des titres
aimés, et un profil de 1 titre aimé + 4 détestés n'est pas plus fiable qu'un profil de 1 titre.
Correction issue de la revue de code (voir plus bas).

### c) Identifiants : MAL dans les modèles, `catalog.media.id` dans l'API
Les modèles (facteurs ALS, features de drop) parlent en **identifiants MAL** : c'est la clé du
dataset d'entraînement. L'API et le front parlent en **`catalog.media.id`** : un identifiant
interne, car les MAL_ID des animes et des mangas se chevauchent. Les conversions se font dans
`backend/app/services/catalog_service.py`, **et nulle part ailleurs**.

### d) Risque de drop : mêmes features qu'à l'entraînement, ou pas de chiffre
- Les infos d'anime (format, épisodes, durée, source, année, classification, popularité, studio,
  genres) sont lues dans `catalog.media`, **seulement pour les animes `data_source =
  'mal_kaggle_2020'`** : ce sont ceux que le modèle a vus à l'entraînement.
- Parité vérifiée sur **tout le catalogue** : les infos servies par l'API ont été comparées à
  celles de l'entraînement (`clean/anime`) pour **16 214 animes** sur **9 colonnes**, avec
  **0 différence** (`reports/exploration_2026-11-20.json`, mesure `api_serving_feature_parity`).
- Les features sont ensuite calculées par `feature_row` puis `prepare_x` du paquet partagé : le
  même code que l'entraînement.
- Un **anime absent des données d'entraînement** (ajouté par Jikan ou AniList) ou un
  **manga/manhwa** reçoit `status: "insufficient_data"` avec un message, **jamais un chiffre**
  (SPEC § 6.4). Un chiffre calculé sur des features vides serait inventé.
- Vérifié sur les vraies données : avec 5 animes complétés, la probabilité de drop de Death Note
  est de 0,0178, pour un seuil de 0,2406 (`reports/exploration_2026-11-20.json`, mesure
  `api_real_data_smoke`).

### e) SQLAlchemy 2 synchrone + psycopg 3, lecture seule
L'API **lit** les schémas `catalog` et `mart`. Ils appartiennent au pipeline, qui les crée et les
remplit (ADR 003). Les classes de `backend/app/db/models.py` décrivent les colonnes lues ; elles
ne créent jamais de table. Alembic (phase 7) ne gérera que le schéma `app`.

Pourquoi **synchrone** : FastAPI exécute les routes `def` dans un pool de threads. Le code est plus
simple à écrire et à tester qu'en asynchrone, et le calcul des modèles (NumPy, scikit-learn) est
de toute façon synchrone. À ce volume, l'asynchrone n'apporterait rien de mesurable.

### f) Modèles chargés au démarrage, dégradation contrôlée
Les modèles sont chargés une fois, dans le `lifespan` de FastAPI (au démarrage), puis gardés en
mémoire.
- Si un modèle est absent ou invalide, **l'API démarre quand même**. Les routes qui en ont besoin
  répondent **503** (« service indisponible, réessayer plus tard ») et non 500.
- `GET /health` répond toujours 200 tant que le processus tourne, avec `status: "degraded"` si la
  base ou un modèle manque (vivacité). `GET /health/ready` répond **503** dans ce cas
  (disponibilité : prêt à recevoir du trafic ?).
- La fiche est **validée au chargement**, pas à la première requête : clés obligatoires présentes,
  et pour le drop, colonnes du pickle (`feature_names_in_`) **égales au contrat** de la fiche.
  Une fiche incomplète rend le modèle indisponible dès le démarrage.

Pourquoi ne pas planter au démarrage : dans Docker, un conteneur qui plante redémarre en boucle.
Une API « degraded » reste utilisable (catalogue, tendances) et dit clairement ce qui manque.

### g) Jikan : appel externe encadré
`/trending` appelle Jikan (saison en cours) pendant la requête. Jikan est public, sans clé, limité
à 3 requêtes/s et 60/min, et renvoie parfois 429 ou 5xx (`config/settings.yaml`, `api.jikan`).
- **Timeout** de 5 s par appel (`timeout_s`).
- **Retries** : 2 (`max_retries`), sur les erreurs réseau, 429 et 5xx, avec attente croissante
  (1 s, puis 2 s) ou l'en-tête `Retry-After` s'il est fourni (plafonné à 10 s dans le code).
- **Cache** en mémoire d'une heure (`cache_seconds: 3600`) : la saison change peu dans l'heure.
- **Réponse périmée** : si Jikan tombe alors qu'une réponse est en cache, l'API sert la dernière
  connue avec `stale: true`.
- **Délai après échec** : après un échec, pas de nouvel essai avant 120 s (`failure_backoff_s`).
  Sans ça, chaque requête relancerait toute la séquence de retries pendant une panne.
- **Un seul rafraîchissement à la fois**, sans bloquer les autres requêtes : si une réponse
  existe, les autres requêtes la reçoivent tout de suite au lieu d'attendre.
- **Filtre adulte** : paramètre `sfw=true` côté Jikan, puis revérification avec la règle de
  l'ADR 002 (rating `Rx` ou genre Hentai).
- **Aucun en-tête identifiant** : User-Agent par défaut de httpx, rien sur le projet.

Pire cas mesuré quand Jikan ne répond pas (`reports/exploration_2026-11-20.json`, mesure
`api_jikan_worst_case`) :

| Réglage | Temps avant le 503 |
|---|---|
| Avant : timeout 10 s, 3 retries | 47,2 s |
| Après : timeout 5 s, 2 retries | 18,2 s |

Ensuite, pendant 120 s, la réponse est immédiate : la dernière saison connue (`stale: true`) s'il
y en a une en cache, sinon le 503, sans nouvel appel à Jikan.

**Jikan était injoignable pendant toute la phase** (aussi depuis Windows, hors WSL). `/trending`
n'a donc été vérifié qu'avec un **Jikan simulé** dans les tests. À revérifier en conditions
réelles.

### h) Sécurité
- **Validation Pydantic** de toutes les entrées : identifiants > 0, notes entre 1 et 10, `k` ≥ 1
  et plafonné à `max_k` (50), recherche de 2 à 100 caractères, listes de **500 éléments au plus**
  (`max_list_items`), **doublons refusés** dans une liste. Entrée invalide → 422.
- **Recherche** : `ILIKE` paramétré par SQLAlchemy (pas de SQL construit à la main) ; les jokers
  `%` et `_` sont échappés pour chercher le texte tel quel. Une recherche réduite à des espaces est
  refusée (sinon tout le catalogue correspondrait).
- **CORS** restreint aux origines configurées (le front), méthodes GET et POST seulement ; jamais
  `*`.
- **Base indisponible → 503**. Seul le **nom** de l'erreur est journalisé : son message peut
  contenir l'URL de connexion (et donc le mot de passe).
- **Conteneur non-root** (utilisateur uid 10001 ; `reports/exploration_2026-11-20.json`,
  `api_docker_image.runs_as_uid`).
- **Modèles montés en lecture seule** (`./models:/models:ro`).
- **Ports liés à 127.0.0.1** : ni la base ni l'API ne sont exposées sur le réseau local.
- Le pickle de drop n'est chargé que si son sha256 correspond à la fiche. Le sha256 prouve
  l'intégrité, pas l'authenticité (ADR 005).

### i) Docker
- **Build multi-étapes avec uv** : une première étape construit l'environnement Python
  (`uv sync --frozen`, dépendances d'abord pour profiter du cache) ; l'image finale ne garde que
  ce venv, sans uv ni outils de build.
- **Contexte de build = racine du dépôt**, car le backend dépend de `packages/tsuzuku-ml`. Or la
  racine contient `data/` (plusieurs Go) et `models/`. Le `.dockerignore` est donc une **liste
  blanche** : tout est exclu (`*`), sauf ce dont l'image a besoin (code du backend, paquet partagé,
  `config/settings.yaml`).
- **Profil compose `api`** : `make up` ne lance que la base ; `make api-up` construit et lance
  l'API (http://localhost:8000/docs).
- **Taille de l'image : 1,02 GB**, sans PySpark (`reports/exploration_2026-11-20.json`, mesure
  `api_docker_image`). Le poids vient surtout de NumPy, pandas, pyarrow et scikit-learn, tous
  nécessaires au fold-in et au modèle de drop.
- **CI** (`.github/workflows/ci-backend.yml`) : un job `docker` construit l'image et la démarre
  **sans base ni modèles**. `/health` doit répondre 200 avec `"degraded"` et `/health/ready` 503 :
  on vérifie que l'API ne plante pas au démarrage.

## Alternatives écartées
- **Copier le code ML dans le backend** (prévu par l'ADR 005) : deux copies finissent par
  diverger. Un test peut le détecter, mais un seul fichier l'empêche.
- **Faire dépendre le backend du paquet `pipeline`** : il tirerait PySpark (et une JVM) dans
  l'image de l'API, pour rien.
- **SQLAlchemy asynchrone** : plus complexe à écrire et à tester, sans gain mesurable ici (voir e).
- **Appeler Jikan sans cache** : chaque visite de la page d'accueil coûterait 1 à 4 appels, avec
  un risque de 429, et une panne de Jikan ralentirait toutes les requêtes.
- **Servir un chiffre de drop pour un anime récent** : ses features seraient vides ou différentes
  de l'entraînement. Le chiffre aurait l'air sérieux mais serait inventé.

## Limites et suites
- **Jikan non vérifié en réel** : injoignable pendant toute la phase (voir g).
- **Image volumineuse** (1,02 GB). Pistes : dépendances plus fines, image de base plus légère.
- **Pas d'authentification** avant la phase 7 : le mode démo n'enregistre rien, le profil est
  dans la requête.
- **`parity_check` exige l'égalité stricte du top 10**. Un écart de calcul flottant entre deux
  machines (autre processeur, autre bibliothèque d'algèbre linéaire) pourrait changer un ex æquo
  et désactiver le modèle de reco au démarrage (503). Pas observé à ce jour ; à surveiller lors
  du déploiement cloud.
- **Recherche en `ILIKE '%…%'`** : pas d'index utilisable, parcours de la table. Suffisant à ce
  volume ; un index trigramme (`pg_trgm`) viendra plus tard.

## Vérification sur les vraies données
Source : `reports/exploration_2026-11-20.json`, mesure `api_real_data_smoke` (base de dev, run
reco `1263a415`, run drop `3e8b164f`).
- Profil de démonstration de la phase 4 (6 titres) : stratégie `als`, et **top 10 identique** à
  celui de la phase 4 (clé `showcase` de `reports/reco_metrics.json`).
- Avec 3 titres aimés : stratégie `popularity`.
- Risque de drop de Death Note avec 5 animes complétés : 0,0178, seuil 0,2406 (pas à risque).

## Corrections issues de la revue de code
**HIGH**
- **Anime récent → `insufficient_data`** : un anime ajouté après le dataset recevait un chiffre
  calculé sur des features vides.
- **Règle des 5 sur les titres AIMÉS** : des titres mal notés comptaient dans les 5. Et le
  « parce que tu as aimé X » ne cite **jamais** un titre détesté (il ne cherche que parmi les
  titres aimés).
- **Jikan** : le verrou ne bloque plus les autres requêtes quand une réponse existe ; délai après
  échec ajouté (sans lui, une panne relançait les retries à chaque requête).

**MEDIUM**
- **Base indisponible → 503** (au lieu de 500), sans URL dans les logs.
- **Démarrage robuste** à un pickle invalide (l'API démarre en « degraded ») ; fiche validée au
  chargement (clés, colonnes du pickle = contrat).
- **Doublons refusés** dans une liste du risque de drop.
- **Corps Jikan non JSON** (page HTML d'un proxy, par exemple) traité comme une panne.

**LOW**
- Recherche réduite à des espaces refusée.
- `Retry-After` ignoré au dernier essai (attendre ne servait à rien).
- `k` résultats garantis quand des recos n'ont pas de fiche au catalogue (marge de candidats).
- Route `/health/ready` ajoutée (disponibilité), à côté de `/health` (vivacité).
- Docstring corrigée ; fichier parasite supprimé.
