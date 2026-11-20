# ADR 007 — Airflow : ingestion quotidienne Jikan et synchro hebdomadaire AniList

**Date** : 2026-11-20 · **Statut** : accepté (choix validés par Royston)

## Contexte
Le dataset Kaggle s'arrête début 2020. Pour avoir des **données fraîches**, la SPEC (§ 9) prévoit
deux DAG Airflow, lancés par docker-compose (Airflow 2.x) :
- `jikan_daily_ingest` (quotidien) : saison en cours + watchlist → `catalog.media_daily_stats`,
  avec upsert idempotent, contrôle qualité, et « un échec isolé ne fait pas tomber le DAG » ;
- `anilist_catalog_sync` (hebdomadaire) : catalogue manga / manhwa (+ embeddings des nouvelles
  œuvres, reporté en phase 10).

Critère de fin de la phase (SPEC § 10) : **les 2 DAG tournent dans docker-compose, 1re exécution
réussie**.

**Jikan était en panne pendant la phase** : injoignable depuis la machine et aussi de l'extérieur
(comme en phase 5, ADR 006). Décision de Royston le 2026-11-20 : le DAG Jikan est codé selon la
SPEC et testé avec des réponses simulées ; sa 1re exécution réelle est à refaire au retour de
Jikan. La phase se clôt avec **AniList exécuté pour de vrai**.

## Décisions

### a) Airflow 2.11, LocalExecutor, base de métadonnées sur le même Postgres
- **Airflow 2.11.0** (dernière version 2.x, la SPEC demande 2.x), image officielle Python 3.11
  (`infra/airflow/Dockerfile`).
- **LocalExecutor** : le scheduler lance les tâches lui-même, en processus locaux. Deux DAG
  linéaires, quelques tâches par jour : pas besoin de workers séparés.
- **Métadonnées d'Airflow** (runs, états des tâches, utilisateurs) dans une base `airflow` sur le
  **même serveur Postgres** que Tsuzuku. Le service `airflow-db` crée cette base si elle manque :
  le script d'init de Postgres ne tourne qu'à la **création du volume**, il ne suffit pas pour une
  base de dev déjà remplie.
- Services du profil compose `airflow` : `airflow-db` (création de la base), `airflow-init`
  (migration du schéma d'Airflow + compte admin), `airflow-webserver`, `airflow-scheduler`.
- Les DAG démarrent **actifs** (`DAGS_ARE_PAUSED_AT_CREATION=false`) : ils tournent sans action
  manuelle.

### b) Image dédiée : le pipeline installé SANS PySpark
L'ingestion n'utilise que httpx, psycopg et pyyaml. Installer tout le pipeline tirerait PySpark,
une JVM et scikit-learn dans l'image, pour rien.
- Le paquet `pipeline` est installé avec **`--no-deps`** ; ses dépendances réellement utilisées
  sont listées à la main (httpx, psycopg, python-dotenv, pyyaml).
- Le **fichier de contraintes d'Airflow** fige les versions compatibles : une dépendance ajoutée
  ne peut pas casser Airflow.
- Un test le garantit : `pipeline/tests/test_ingestion_no_spark.py` importe les modules
  d'ingestion dans un sous-processus et échoue si un module `pyspark` est chargé.
- **Ce test a trouvé un vrai problème** : `MEDIA_COLUMNS` vivait dans le module Spark
  `spark/build_catalog.py`, et `db/loader.py` (utilisé par l'ingestion) l'importait. Résultat :
  PySpark était importé indirectement. `MEDIA_COLUMNS` a été **déplacé dans `db/loader.py`** ; le
  module Spark le ré-exporte.
- `TSUZUKU_ROOT=/opt/tsuzuku` : dans l'image, le paquet est dans `site-packages`. Cette variable
  dit au code où sont montés `config/`, `data/raw` et `reports/`.
- Contexte de build = racine du dépôt, avec une **liste blanche**
  (`infra/airflow/Dockerfile.dockerignore`) : seuls `pipeline/pyproject.toml` et `pipeline/src`
  entrent dans le contexte, pas `data/` (plusieurs Go).

### c) DAG minces, code métier testé hors Airflow
Les fichiers `pipeline/dags/*.py` ne font qu'enchaîner des tâches. Tout le code (appels HTTP,
conversion, chargement, contrôles) vit dans `tsuzuku_pipeline.ingestion` et se teste avec pytest,
**sans Airflow** : réponses simulées (`httpx.MockTransport`), horloge et attente simulées.

| DAG | Planning | Tâches |
|---|---|---|
| `jikan_daily_ingest` | tous les jours à 06:00 UTC | `collect` → `fetch_stats` → `load` → `quality_check` |
| `anilist_catalog_sync` | le lundi à 05:00 UTC | `fetch_pages` → `load` → `quality_check` |

Retries : 2 essais de plus (10 min d'écart) pour Jikan, 1 (15 min) pour AniList ;
**`quality_check` jamais réessayé** : un contrôle en échec ne se corrige pas en réessayant.
`max_active_runs=1` : deux exécutions du même DAG ne se chevauchent pas.

### d) Atterrissage brut daté : une tâche se relance seule
Chaque tâche écrit ses résultats dans **`data/raw/<source>/<date>/`** (`targets.json`,
`stats.json`, `pages.json`, `load.json`) et la tâche suivante les relit.
- Une tâche se **relance seule** (« clear » dans Airflow) sans rappeler l'API : `load` relit le
  fichier brut.
- La donnée brute reste disponible pour **rejouer un chargement** ou déboguer.
- **Écriture atomique** : le fichier est écrit sous un nom temporaire puis renommé. La tâche
  suivante ne lit jamais un fichier à moitié écrit.
- Les données ne passent **pas par XCom** (seuls de petits compteurs y sont renvoyés).

### e) Idempotence : relancer ne crée aucun doublon
- Statistiques Jikan : **upsert sur (`snapshot_date`, `media_id`)** (clé primaire de
  `catalog.media_daily_stats`). Relancer le même jour met la ligne à jour.
- Catalogue AniList : **upsert sur `anilist_id`** (colonne unique).
- Animes Jikan : rattachés par la contrainte (`kind`, `mal_id`).
- Une **transaction par chargement** : rien de partiel n'est visible par l'API ou Power BI.
- **Prouvé sur les vraies données** : la 2e exécution AniList sur le même intervalle a donné
  **0 insertion et 5 000 mises à jour** (`reports/exploration_2026-11-20.json`, mesure
  `anilist_first_runs`, clé `run_2_same_interval`).

### f) Protection des données d'entraînement et aucune suppression
- Les lignes du dataset 2020 (`data_source = 'mal_kaggle_2020'`) servent de **features au modèle
  de drop** (ADR 006, d). Jikan n'y complète **que `cover_url`** (absente du dataset) **et
  `airing_status`** (statut de diffusion à jour). Les colonnes-features (format, épisodes, studios, popularité…) ne sont
  **jamais modifiées**. Testé : `test_jikan_full_run_and_training_rows_protected`.
- Un anime absent du catalogue est inséré avec `data_source = 'jikan'` ; un titre AniList avec
  `data_source = 'anilist'`.
- **Aucune œuvre n'est supprimée** par les DAG : les listes des utilisateurs (phase 7) pointeront
  sur `catalog.media.id`.
- **Exception unique** : après la revue de code, les **148 romans** chargés par la 1re exécution
  AniList ont été supprimés de la base de dev (`anilist_first_runs.novels_removed_after_review`).
  C'était avant toute donnée utilisateur : aucune liste ne pouvait pointer dessus. Ce nettoyage
  ponctuel ne se reproduira pas une fois les comptes ouverts.

### g) Dates : date logique = heure de déclenchement
- Les deux DAG utilisent **`CronTriggerTimetable`**. La date logique d'un run est **l'heure à
  laquelle il est déclenché** : 06:00 du jour pour un run planifié, l'instant du clic pour un run
  manuel.
- Avec le planning cron « classique » d'Airflow 2, la date logique est le **début de
  l'intervalle** : un run manuel est daté de la veille (Jikan) ou du lundi précédent (AniList).
  C'est ce qui est arrivé aux 2 premières exécutions AniList : lancées le 2026-11-20, elles ont
  produit `anilist_2026-11-16.json`.
- **Refus de collecter Jikan pour une date passée** : Jikan ne donne que l'état **actuel**.
  Collecter « pour hier » rangerait les chiffres d'aujourd'hui sous la date d'hier et écraserait
  le vrai snapshot. `collect` et `fetch_stats` échouent donc si la date n'est pas aujourd'hui (UTC) ;
  `load` et `quality_check` restent rejouables (ils lisent les fichiers bruts).
- `catchup=False` : pas de rattrapage des jours manqués (impossible de toute façon avec Jikan).

### h) Respect des limites de débit : un client « poli » commun
`pipeline/src/tsuzuku_pipeline/ingestion/http.py`, utilisé par les deux sources :
- **Intervalle minimum** entre deux appels (`min_interval_s`) ;
- **Retries** sur erreur réseau, 429 et 5xx, avec **attente croissante** (1 s, 2 s, 4 s…,
  plafonnée à 60 s) ; l'en-tête **`Retry-After`** prime s'il est fourni ;
- **`X-RateLimit-Remaining` / `X-RateLimit-Reset`** : quand le quota restant tombe à 0, le client
  attend la remise à zéro **avant** d'appeler, plutôt que de provoquer un 429 ;
- une erreur 4xx (hors 429) n'est pas réessayée ; aucun en-tête identifiant n'est envoyé.

Réglages (`config/settings.yaml`, section `ingestion`) :

| Source | Intervalle | Timeout | Retries | Limite de la source |
|---|---|---|---|---|
| Jikan | 1,0 s (1 req/s) | 15 s | 4 | 3 req/s et 60/min (SPEC § 2.2) |
| AniList | 2,1 s | 30 s | 4 | 30 req/min, lue dans l'en-tête `X-RateLimit-Limit` le 2026-11-20 |

2,1 s entre deux appels reste sous 30 par minute.

### i) Jikan : saison, watchlist, échec isolé
- `collect` : `/seasons/now` (au plus `max_season_pages` = 6 pages) + les animes de
  `config/watchlist.yaml` (identifiants vérifiés, jamais devinés ; liste vide à ce jour). Contenus
  adultes écartés (`sfw=true` + règle de l'ADR 002).
- `fetch_stats` : `/anime/{id}/statistics` pour chaque anime.
- **Échec isolé** : si un anime échoue, il est noté dans `stats.json` et **garde une ligne avec
  son score et ses membres** (lus dans sa fiche), sans le détail par statut. Il reste ainsi dans
  le snapshot du jour (et dans `/trending`).
- **Arrêt anticipé** : dès que les échecs dépassent `max_failure_share` = 20 % des animes, la
  tâche s'arrête et échoue. Ce n'est plus un échec isolé mais une panne ; inutile d'enchaîner des
  heures de retries.
- Colonne **`in_season`** dans `catalog.media_daily_stats` : vrai pour un anime de la saison, faux
  pour un anime de la watchlist.

### j) AniList : quels titres, quel type, quels tags
- Les **5 000 titres les plus populaires** : 100 pages de 50 (`max_pages`, `per_page`), triés par
  popularité décroissante. Validé par Royston le 2026-11-20.
- **Type d'œuvre par pays d'origine** : JP → manga, KR → manhwa, CN et TW → manhua. Autre pays :
  titre ignoré.
- **Romans exclus** : chez AniList, `type: MANGA` couvre aussi les light novels. Exclus dans la
  requête (`format_not_in: [NOVEL]`) et revérifiés dans le code. Les **one-shots** (histoire en un
  chapitre) sont des mangas : gardés.
- **Contenus adultes exclus** : `isAdult: false` dans la requête, puis genre Hentai revérifié.
- **Tags** : gardés si leur pertinence AniList est ≥ `tag_min_rank` = 60 (sur 100) et s'ils ne
  sont pas adultes. Ils serviront aux recos par contenu (phase 10).
- **`idMal` fourni par AniList**, jamais deviné (CLAUDE.md § 6). Si cet identifiant MAL est déjà
  porté par une autre œuvre du même type, il est **mis à null** pour ce titre au lieu de faire
  échouer tout le chargement, et c'est **compté** (`mal_id_cleared`).
- **Popularité = rang dans le tri** (1 = le plus populaire) : même sens que le rang MAL des animes,
  pour que « trier par popularité » ait un sens dans tout le catalogue.
- Un titre **sorti du top** garde sa fiche mais son rang est remis à **NULL** : un rang périmé
  donnerait deux titres au même rang.

### k) Contrôles qualité et rapport par exécution
La dernière tâche de chaque DAG vérifie en base et écrit un rapport JSON dans
`reports/ingestion/<source>_<date>.json` (ignoré par git ; les chiffres retenus sont recopiés dans
`reports/exploration_2026-11-20.json`).
- Jikan : des lignes existent pour le jour, toutes les stats récupérées sont chargées, aucun
  compteur négatif, aucun contenu adulte.
- AniList : au moins `min_share_of_expected` = 90 % des titres attendus, **tous les titres gardés
  présents en base** (vérifié par requête sur leurs `anilist_id`), aucun contenu adulte.
- Contrôle en échec → la tâche échoue, visible en rouge dans Airflow.

### l) `/trending` lit la base
Depuis cette phase, `/trending` (`backend/app/services/trending_service.py`) sert le **snapshot du
DAG** : `catalog.media_daily_stats`, dernier jour disponible, filtré sur `in_season` (la saison,
pas la watchlist), trié par nombre de membres. Rapide, et aucune API externe pendant la requête.
L'appel direct à Jikan de la phase 5 ne sert plus qu'en **repli** : snapshot absent, vide, de plus
de `trending_max_age_days` = 2 jours, ou table pas encore créée. La réponse indique son origine
(`origin` : `database` ou `live`).

### m) Secrets
- `make airflow-keys` (`infra/airflow/gen_keys.py`) ajoute à `.env` les valeurs manquantes :
  clé **Fernet** (chiffre les connexions et variables stockées par Airflow), clé secrète du
  webserver (signe les cookies de session), compte admin avec **mot de passe aléatoire**, UID de
  l'hôte. Les valeurs ne sont **jamais affichées** ; une valeur déjà présente n'est jamais
  remplacée.
- Dans `docker-compose.yml`, ces variables sont écrites `${VAR:-}` et non `${VAR:?}` : compose
  évalue **tout le fichier**, même pour un profil inactif. Avec `:?`, `make up` (la base seule)
  exigerait les clés d'Airflow. C'est donc `make airflow-up` qui vérifie qu'elles sont définies
  avant de démarrer.

### n) Sécurité des montages
- Écriture limitée au strict nécessaire : **`data/raw/jikan`, `data/raw/anilist` et
  `reports/ingestion`**. Les DAG et `config/` sont montés en lecture seule. Un bug d'ingestion ne
  peut toucher ni les CSV Kaggle ni les rapports de métriques qui alimentent le README.
- Conteneurs lancés avec l'**UID de l'hôte** : les fichiers écrits appartiennent à l'utilisateur,
  pas à root.
- Interface web liée à **127.0.0.1:8080** : pas exposée sur le réseau local.

### o) CI
`.github/workflows/ci-airflow.yml` : construit l'image, puis charge les DAG dans l'image avec une
base **SQLite jetable** (`DagBag`, `pipeline/tests/test_dags.py`) : aucune erreur d'import,
exactement les 2 DAG attendus, bonnes tâches dans le bon ordre, bon planning, `catchup` désactivé.
Comme PySpark n'est pas dans l'image, une importation indirecte de Spark ferait échouer ce job.
`make airflow-test` fait la même chose en local, sans Postgres.

## Résultats
### AniList : exécuté pour de vrai
Source : `reports/exploration_2026-11-20.json`, mesure `anilist_first_runs` (rapports
`reports/ingestion/anilist_2026-11-16.json` et `anilist_2026-11-20.json`, plus requêtes SQL).

| Exécution | Titres récupérés | Insérés | Mis à jour | Contrôles |
|---|---|---|---|---|
| 1 (planifiée) | 5 000 (100 pages) | 5 000 | 0 | OK |
| 2 (relance, même intervalle) | — | 0 | 5 000 | OK |
| 3 (après la revue : romans exclus, date = jour réel) | 5 000 | 148 | 4 852 | OK |

- 1re exécution : 0 doublon, 0 `idMal` mis à null, 0 titre écarté ; tâche `fetch_pages` :
  **3,5 minutes** (`fetch_task_minutes_run_1`).
- 3e exécution : 0 titre écarté, 0 rang remis à NULL. Les 148 insertions remplacent les 148
  romans supprimés : 148 nouveaux titres entrent dans le top 5 000 une fois les romans exclus.
- Catalogue AniList final : **3 715 mangas, 1 103 manhwas, 182 manhuas** (`catalog_by_kind`).
  Avant l'exclusion des romans : 3 753, 1 075 et 172 (`catalog_by_kind_run_1`).
- Tags : **344** tags utilisés, **36 233** liens œuvre-tag (`tags_used_after_run_3`,
  `media_tag_links_after_run_3`).
- `catalog.media` : **16 214** animes du dataset 2020 + **5 000** titres AniList
  (`catalog_rows_by_source`).
- Limite de débit lue : `X-RateLimit-Limit` = **30** (`rate_limit_header_x_ratelimit_limit`).

### Jikan : 1re exécution réelle à refaire
Source : `reports/exploration_2026-11-20.json`, mesure `jikan_first_run`. Le 2026-11-20, la tâche
`collect` a échoué à ses **2 premiers essais** (Jikan injoignable : timeout, aussi hors WSL) ; le
DAG était en attente d'un nouvel essai. Le DAG n'est donc **vérifié qu'avec des réponses
simulées** (`pipeline/tests/test_ingestion_jobs.py` : exécution complète, relance idempotente,
échec isolé, arrêt anticipé, date passée refusée, données d'entraînement protégées). Sa 1re
exécution réelle est à refaire au retour de Jikan.

## Alternatives écartées
- **CeleryExecutor + Redis** : workers répartis sur plusieurs machines. Inutile pour deux DAG
  linéaires sur une machine ; deux services de plus à faire tourner et surveiller.
- **Installer tout le pipeline (avec PySpark) dans l'image** : image beaucoup plus lourde, JVM
  inutile, conflits de versions avec Airflow. Le test `test_ingestion_no_spark` rend la séparation
  vérifiable.
- **Transporter les données par XCom** : XCom stocke ses valeurs dans la base d'Airflow ; il est
  fait pour de petits messages, pas pour 5 000 fiches. Les fichiers bruts datés permettent en plus
  de rejouer une tâche seule.
- **Supprimer les titres sortis du top AniList** : les listes des utilisateurs pointeront dessus.
  On remet seulement leur rang à NULL.
- **Rattrapage (`catchup`)** : Jikan ne donne pas l'historique. Rattraper un jour passé
  rangerait les chiffres d'aujourd'hui sous une mauvaise date.
- **AniList comme source de repli pour les stats d'anime quand Jikan est en panne** : AniList a
  une autre population d'utilisateurs que MyAnimeList. Mélanger les deux dans la même série de
  stats la rendrait incohérente (les membres et scores ne se comparent pas).

## Limites et suites
- **Jikan non validé en réel** : 1re exécution à refaire au retour de Jikan.
- **Embeddings des nouvelles œuvres** : prévus par la SPEC dans `anilist_catalog_sync`, ajoutés
  en phase 10 (recos par contenu).
- **Même utilisateur Postgres pour Airflow et Tsuzuku en dev** : Airflow peut techniquement lire
  la base de Tsuzuku. Acceptable en local ; en production, l'ingestion tournera via Cloud
  Scheduler → Cloud Run Job (SPEC § 9), avec ses propres identifiants.
- **Airflow 3 non utilisé** : la SPEC demande Airflow 2.x.
- **Watchlist vide** : `config/watchlist.yaml` ne contient encore aucun anime.

## Corrections issues de la revue de code
**HIGH**
- **Dates des runs manuels** : avec le planning cron classique, un run manuel était daté de la
  veille (Jikan) ou du lundi précédent (AniList), et aurait pu écraser le snapshot d'un autre
  jour. Passage à `CronTriggerTimetable` et refus de collecter Jikan pour une date passée (voir g).

**MEDIUM**
- **Échec isolé gardé dans le snapshot** : un anime dont `/statistics` échoue garde sa ligne avec
  score et membres, au lieu de disparaître de `/trending`.
- **Repli de `/trending` sur table absente** : si `catalog.media_daily_stats` n'existe pas encore,
  l'API se rabat sur Jikan au lieu de répondre en erreur.
- **Même périmètre « saison » pour les deux sources de `/trending`** : colonne `in_season`, pour
  que le snapshot en base (sans la watchlist) corresponde à l'appel direct (`/seasons/now`).
- **Romans exclus** d'AniList (et nettoyage ponctuel des 148 déjà chargés, voir f).
- **Tests des conflits d'`idMal`** : doublon dans le lot, doublon avec un titre déjà en base,
  relance identique.

**LOW**
- Le contrôle `all_loaded` ne contrôlait rien de réel : remplacé par une vérification en base
  (tous les titres gardés présents, par `anilist_id`).
- Arrêt anticipé de `fetch_stats` au-delà de `max_failure_share`.
- `make airflow-test` tourne sans base (SQLite jetable), comme la CI.
- Montages en écriture restreints aux 3 dossiers nécessaires (voir n).
- Rang de popularité remis à NULL pour un titre sorti du top.

**Test des DAG qui passait « par accident »** : `test_dags.py` lisait les DAG **sérialisés dans
la base d'Airflow**. Une base déjà remplie le faisait passer même si les fichiers étaient
introuvables. Corrigé : il lit les **fichiers** (`read_dags_from_db=False`) et exige
**exactement** les 2 DAG.
