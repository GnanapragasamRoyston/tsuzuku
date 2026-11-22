# SPEC — Tsuzuku

## 1. Vision

**Tsuzuku** est une appli web de suivi d'animes, de mangas et de manhwas, dans l'esprit de Letterboxd, avec trois fonctionnalités que les sites existants n'ont pas :

1. **Recommandations personnalisées par IA**, entraînées sur 109 M d'interactions réelles.
2. **Risque de drop** : « Probabilité que tu lâches cette série : 72 % ».
3. **Épisode critique** : « La plupart des gens qui lâchent le font à l'épisode 3. Ceux qui passent l'épisode 5 vont presque tous au bout. »

Argument recruteur : sous le capot, le risque de drop est un **modèle de churn**, le même problème que la résiliation en assurance, en banque ou dans les télécoms. Le projet montre une boucle complète : données → pipeline → modèles → API → produit → nouvelles données.

Priorité : **le moteur Data/ML d'abord** (phases 0 à 6 = version minimale montrable), l'appli ensuite.

## 2. Sources de données

### 2.1 Historique anime — Kaggle « Anime Recommendation Database 2020 » (hernan4444)
- `animelist.csv` : user_id, anime_id, score, watching_status, watched_episodes — ≈ 109 M lignes, 17 562 animes, 325 772 utilisateurs.
- `rating_complete.csv` : sous-ensemble Completed + noté (≈ 57 M lignes).
- `anime.csv` : métadonnées. `anime_with_synopsis.csv` : synopsis.
- `watching_status.csv` : correspondance des codes. **Le lire, ne pas supposer les codes.**
- Téléchargement via l'API Kaggle (`~/.kaggle/kaggle.json`, fourni par Royston). Citer la source et la licence.
- **Filtrer les contenus adultes** (`Rating` commençant par `Rx`, ou genre `Hentai`), partout : pipeline, catalogue, appli.

### 2.2 Données fraîches anime — API Jikan v4 (sans clé)
- Limite : 3 req/s et 60 req/min. Viser **1 req/s**, retry + backoff exponentiel sur 429/5xx.
- `GET /seasons/now`, `GET /anime/{id}`, `GET /anime/{id}/statistics`, `GET /manga/{id}/statistics`.

### 2.3 Catalogue manga et manhwa — API GraphQL AniList (sans clé pour la lecture)
- Récupération paginée des mangas (`type: MANGA`) avec `countryOfOrigin` (JP = manga, KR = manhwa, CN = manhua), genres, tags, synopsis, couverture, popularité, `idMal`.
- Respecter la limite indiquée dans les en-têtes de réponse (`X-RateLimit-*`), backoff sur 429.
- **Limite connue** : il n'existe pas de jeu public de millions d'interactions manga/manhwa comparable au dataset anime. Les recos manga/manhwa sont donc d'abord **basées sur le contenu** (§ 6.3), puis enrichies par les interactions des utilisateurs de Tsuzuku. À écrire dans les limites du README.

### 2.4 Données de l'appli
Les listes des utilisateurs Tsuzuku (statut, progression, épisode ou chapitre de drop, note) alimentent les tableaux de bord et, à terme, le réentraînement.

## 3. Architecture

```
                 ┌──────────────── pipeline/ ────────────────┐
Kaggle CSV ──►   PySpark : nettoyage, Parquet, agrégats, features
                   ├─► modèle de drop (scikit-learn) ──────────┐
                   ├─► recommandation ALS (Spark MLlib) ───────┤  artefacts
                   └─► marts analytiques ──► Postgres (mart)   │  (models/ ou GCS)
Jikan + AniList ──► Airflow (quotidien) ──► Postgres (catalog) │
                   embeddings (sentence-transformers) ──► pgvector
                 └───────────────────────────────────────────┘
                                                               ▼
              backend/ FastAPI : auth, listes, catalogue, recos, risque de drop, assistant IA
                                                               ▼
              frontend/ Next.js ◄── utilisateurs        Power BI ◄── vues SQL (mart)
```

Schéma Mermaid à produire dans `docs/architecture.md` et dans le README.

## 4. Arborescence cible (monorepo)

```
tsuzuku/
├── CLAUDE.md
├── README.md
├── Makefile
├── docker-compose.yml            # postgres+pgvector, airflow, backend, frontend
├── .env.example
├── .gitignore                    # data/, models/, .env, *.parquet, node_modules/
├── .github/workflows/
│   ├── ci-pipeline.yml           # ruff, pytest, pip-audit
│   ├── ci-backend.yml            # ruff, pytest, pip-audit, bandit
│   ├── ci-frontend.yml           # lint, typecheck, vitest, npm audit
│   └── deploy.yml                # phase 11
├── config/
│   ├── settings.yaml             # chemins, tailles d'échantillon, seeds, mémoire Spark
│   └── watchlist.yaml
├── data/                         # gitignoré : raw/, parquet/, samples/
├── models/                       # gitignoré : artefacts locaux
├── reports/                      # métriques et figures générées
├── pipeline/
│   ├── pyproject.toml
│   ├── dags/
│   │   ├── jikan_daily_ingest.py
│   │   └── anilist_catalog_sync.py
│   ├── src/tsuzuku_pipeline/
│   │   ├── ingestion/            # kaggle_download, jikan_client, anilist_client
│   │   ├── spark/                # session, to_parquet, quality_checks, drop_curves,
│   │   │                         # retention_stats, build_drop_dataset, build_catalog
│   │   ├── ml/
│   │   │   ├── drop/             # features, train, evaluate, export
│   │   │   └── reco/             # als_train, als_evaluate, export_factors
│   │   ├── embeddings/           # build_media_embeddings
│   │   └── db/                   # schema_mart.sql, views_powerbi.sql, loader
│   ├── notebooks/01_eda.ipynb
│   └── tests/
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                 # config, security (argon2, JWT), rate limiting
│   │   ├── db/                   # session, models SQLAlchemy
│   │   ├── schemas/              # Pydantic
│   │   ├── api/routes/           # auth, users, lists, media, reco, drop, stats, assistant
│   │   └── services/             # reco_service, drop_service, catalog_service, llm_service
│   ├── Dockerfile
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── app/                      # routes Next.js
│   ├── components/
│   ├── lib/                      # client API, hooks TanStack Query
│   └── tests/                    # vitest + playwright
├── powerbi/
│   ├── GUIDE.md
│   ├── measures.dax
│   └── screenshots/
└── docs/
    ├── SPEC.md
    ├── architecture.md
    ├── LEARNING.md
    └── decisions/
```

## 5. Base de données PostgreSQL (+ pgvector)

### Schéma `catalog`
| Table | Contenu |
|---|---|
| `media` | id, kind (`anime` / `manga` / `manhwa` / `manhua`), mal_id, anilist_id, titre, titre_alt, synopsis, nb_episodes / nb_chapitres, statut de diffusion, année, studios ou auteurs, source, rating d'âge, cover_url, popularité |
| `genre`, `media_genre`, `tag`, `media_tag` | genres et tags |
| `media_embedding` | media_id, vector (pgvector) |
| `media_daily_stats` | snapshot_date, media_id, score, members, watching, completed, on_hold, dropped, plan_to_watch |

### Schéma `app`
| Table | Contenu |
|---|---|
| `user` | id, email, pseudo, password_hash, created_at, avatar |
| `list_entry` | user_id, media_id, status (`planning`, `in_progress`, `completed`, `paused`, `dropped`), progress, dropped_at, score (1-10), review, started_at, finished_at, updated_at |
| `follow` | follower_id, followed_id (phase 9, optionnel) |
| `push_subscription` | user_id, endpoint, clés de chiffrement, created_at (phase 12, optionnel) |
| `onboarding_choice` | user_id, media_id, created_at |

### Schéma `mart` (analytique, alimenté par Spark)
| Table | Contenu |
|---|---|
| `drop_curve` | media_id, episode_bucket, nb_drops, part_cumulée |
| `critical_episode` | media_id, episode_critique, episode_point_de_non_retour |
| `retention_by_studio`, `retention_by_genre` | taux_drop, taux_completion, médiane de progression au drop |
| `model_runs` | run_id, date, modèle, hyperparamètres, métriques (JSON) |

Définitions à écrire dans le README :
- taux_drop = dropped / (dropped + completed)
- progression au drop = watched_episodes / episodes (si episodes > 0)
- épisode critique = épisode où la part des drops est maximale ; point de non-retour = premier épisode après lequel le taux de completion des spectateurs restants dépasse un seuil fixé dans `settings.yaml`

## 6. Machine learning

### 6.1 Modèle de drop (churn) — scikit-learn
- **Unité** : couple (utilisateur, anime) au statut Completed ou Dropped. **Cible** : `is_dropped`.
- **Contrainte produit** : chaque feature doit être **calculable pour un utilisateur Tsuzuku** à partir de sa liste. Sinon, elle est interdite.
- **Features** :
  - œuvre : type, nb épisodes, durée, genres (multi-hot), studio (top-N + « other »), source, année, rating d'âge, rang de popularité
  - utilisateur : taille de la liste, part de chaque genre, taux de drop historique **excluant la ligne courante** (leave-one-out), note moyenne donnée
- **Interdit (fuite)** : `watched_episodes`, le score de la ligne, les colonnes agrégées d'`anime.csv` (`Dropped`, `Completed`, `Watching`, `On-Hold`, `Plan to Watch`, `Score`, `Score-*`). ADR obligatoire.
- **Volume** : features construites avec Spark sur tout le dataset, puis échantillon stratifié pour scikit-learn (taille dans `settings.yaml`). Le dire dans le README.
- **Split par utilisateur** (`GroupShuffleSplit`).
- **Modèles** : `DummyClassifier`, `LogisticRegression`, `HistGradientBoostingClassifier`.
- **Métriques** : ROC-AUC, PR-AUC, F1 classe drop, matrice de confusion, calibration. Traiter le déséquilibre des classes.
- **Sorties** : `reports/drop_metrics.json`, figures, `mart.model_runs`, artefact `drop_model.joblib`, importance des variables (permutation) avec 3 lignes d'interprétation.

### 6.2 Recommandation anime — Spark MLlib ALS
- Données : `rating_complete.csv` (notes explicites). Filtrer les utilisateurs et les animes trop peu actifs (seuils dans `settings.yaml`), échantillonner si la RAM l'impose.
- Split par utilisateur : une partie des notes de chaque utilisateur de test est masquée.
- **Modèles comparés** : baseline popularité vs ALS (grille sur rank, regParam).
- **Métriques** : RMSE et métriques de classement (precision@10, recall@10, NDCG@10).
- **Export** : facteurs des animes (`item_factors.parquet`) + métadonnées → backend.
- **Démarrage à froid (nouvel utilisateur Tsuzuku)** : calcul du vecteur utilisateur à la volée par moindres carrés régularisés (« fold-in ») à partir de ses choix d'onboarding et de ses notes. Un choix d'onboarding sans note vaut une note par défaut fixée dans `settings.yaml`. Implémenté en NumPy dans `reco_service`, testé.

### 6.3 Recommandation manga / manhwa et cross-média — contenu
- Embeddings (sentence-transformers, modèle multilingue léger, choix justifié en ADR) de « titre + genres + tags + synopsis » pour chaque `media`, stockés dans pgvector.
- Profil utilisateur = moyenne pondérée (par la note) des embeddings des œuvres aimées, tous types confondus. Recos = plus proches voisins filtrés par type et non déjà vus.
- Permet « Tu as aimé l'anime X → manhwa Y ».
- Évaluation qualitative (exemples commentés) + évaluation quantitative sur les animes via le dataset MAL (comparaison avec ALS).

### 6.4 Risque de drop dans l'appli
- Pour une œuvre d'une fiche : features de l'œuvre + features calculées depuis la liste de l'utilisateur → probabilité.
- Animes : modèle 6.1. Mangas/manhwas : pas de modèle tant que les données manquent ; afficher « pas encore assez de données » plutôt qu'un chiffre inventé.
- Épisode critique : depuis `mart.critical_episode` (animes du dataset), puis depuis les drops des utilisateurs Tsuzuku quand le volume suffit (seuil minimal dans `settings.yaml`).

## 7. Backend FastAPI

- SQLAlchemy 2 + Alembic. Pydantic v2. OpenAPI automatique.
- **Auth** : inscription / connexion par email + mot de passe, hachage argon2, JWT en cookie `httpOnly` + `Secure` + `SameSite=Lax`, rate limiting sur la connexion, CORS restreint à l'URL du front.
- **RGPD** : export de ses données (JSON), suppression du compte et des données associées, page de confidentialité, aucun traceur tiers.

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/logout` | comptes |
| GET / PATCH / DELETE | `/me`, `/me/export` | profil, réglage du profil public (phase 9), export, suppression RGPD |
| GET | `/media/search?q=&kind=` | recherche catalogue |
| GET | `/media/{id}` | fiche + stats + épisode critique |
| GET | `/media/{id}/similar` | œuvres proches par le contenu, tous types (phase 10) |
| GET / POST / PUT / DELETE | `/me/list`, `/me/list/{media_id}` | gestion de la liste (GET d'une entrée : phase 9) |
| POST | `/me/onboarding` | choix initiaux |
| GET | `/me/recommendations?kind=` | recos personnalisées |
| GET | `/me/drop-risk/{media_id}` | risque de drop |
| GET | `/trending` | saison en cours (Jikan) |
| GET | `/users/{pseudo}` | profil public, opt-in (privé par défaut, ADR 011) |
| POST | `/me/assistant` | phase 14 |
| GET | `/health` | état API + base |

Tests : `TestClient`, base de test dédiée, couverture des routes d'auth et de liste en priorité.

## 8. Frontend Next.js

Pages :
1. **Accueil** : tendances de la saison, œuvres populaires, appel à s'inscrire
2. **Inscription / connexion**
3. **Onboarding** : choisir au moins 10 œuvres aimées (grille de couvertures avec recherche), filtrable anime / manga / manhwa
4. **Pour toi** : recos par type, chaque carte avec une ligne « pourquoi »
5. **Fiche œuvre** : couverture, infos, bouton d'ajout à la liste, **risque de drop**, **courbe de drop + épisode critique**, stats de la communauté
6. **Ma liste** : onglets par statut, progression, saisie « lâché à l'épisode / chapitre X »
7. **Profil public** : stats perso (genres favoris, taux de drop, nb d'épisodes vus), dernières notes
8. **Paramètres** : export et suppression des données

Exigences : responsive (mobile d'abord), mode sombre, chargement rapide, accessibilité de base (contrastes, labels, navigation clavier). Couvertures servies depuis les URLs Jikan/AniList, avec la source créditée en pied de page. Tests : Vitest (composants), Playwright (inscription → onboarding → recos → ajout à la liste).

### 8.1 Application installable (PWA)

- **Pourquoi** : rendre Tsuzuku installable sur téléphone sans passer par les stores. Publier sur les stores est payant (App Store : 99 $ par an ; Google Play : 25 $ une fois, plus 12 testeurs pendant 14 jours pour un nouveau compte personnel). La PWA coûte 0 € et garde une seule base de code (ADR 010).
- **Manifest** (`app/manifest.ts`, App Router) : nom « Tsuzuku », nom court, `lang: "fr"`, `display: "standalone"`, `start_url`, `scope`, `theme_color` et `background_color` tirées de `docs/DESIGN.md`. Icônes 192 et 512 px (dont une version `maskable`) et `apple-touch-icon` 180 px.
- **Service worker** : bibliothèque maintenue, compatible avec Next.js App Router (Serwist ou équivalent ; choix justifié dans un ADR).
  - coquille de l'appli et fichiers statiques : cache-first ;
  - GET du catalogue, de la fiche œuvre et de « Ma liste » : stale-while-revalidate ;
  - jaquettes : cache limité en nombre d'entrées et en durée ;
  - jamais de cache pour l'authentification, les données privées d'un autre utilisateur ni les requêtes qui modifient des données ; les réponses du compte sont effacées du cache à la déconnexion et à la suppression du compte (appareil partagé) ;
  - page de secours hors ligne, dans le ton de `DESIGN.md`.
- **Hors ligne** : « Ma liste » et les fiches déjà vues restent consultables, avec la date de dernière synchro affichée. Les modifications hors ligne sont désactivées dans un premier temps, avec un message clair ; la synchro différée viendra plus tard, en option.
- **Installation** :
  - Android / Chrome : bouton « Installer l'appli » via `beforeinstallprompt`, proposé après une action utile, jamais à la première visite ;
  - iPhone / Safari : détection hors mode standalone, puis mini-guide « Partager → Sur l'écran d'accueil » ;
  - page `/installer` qui explique les deux.
- **Notifications push** (optionnel, fin de phase) : Web Push avec clés VAPID dans `.env`, table `app.push_subscription`, consentement explicite. Exemples : nouvel épisode d'une série suivie (données Jikan quotidiennes), approche de l'épisode critique. Sur iPhone, ça ne marche que si l'appli est installée. Les abonnements sont inclus dans l'export et la suppression RGPD.
- **Vérification** :
  - critères d'installabilité contrôlés dans Chrome DevTools (onglet Application) ;
  - Lighthouse pour les performances et l'accessibilité (pas de « score PWA » : cette catégorie n'existe plus dans Lighthouse) ;
  - test Playwright du mode hors ligne ;
  - test manuel par Royston sur un vrai Android et un vrai iPhone.
- **Hors périmètre** (à noter dans les limites du README) : publication sur les stores. Pistes futures : Google Play en empaquetant la PWA (TWA, via Bubblewrap ou PWABuilder) ; App Store via Capacitor.

## 9. Orchestration et déploiement

- **Airflow** (docker-compose) :
  - `jikan_daily_ingest` (quotidien) : saison en cours + watchlist → `media_daily_stats` (upsert idempotent, contrôle qualité, un échec isolé ne fait pas tomber le DAG)
  - `anilist_catalog_sync` (hebdomadaire) : catalogue manga/manhwa + recalcul des embeddings des nouvelles œuvres
- Le traitement Spark de l'historique Kaggle et l'entraînement sont des **batchs ponctuels** (`make spark`, `make train`, `make reco`). ADR.
- **Production** (phase 11) :
  - frontend sur Vercel
  - backend sur Google Cloud Run (image Docker)
  - Postgres managé Neon (avec pgvector)
  - artefacts de modèles sur Google Cloud Storage
  - ingestion quotidienne en production : même code, lancé par Cloud Scheduler → Cloud Run Job (Airflow reste l'orchestrateur de dev et de démo ; ADR)
  - Vérifier les offres gratuites au moment du déploiement et poser des alertes de budget sur GCP.

## 10. Phases

Chaque phase : `/plan` → validation de Royston → `/tdd` → `/code-review` → commit → entrée `LEARNING.md`.

| # | Phase | Critère de fin |
|---|---|---|
| 0 | Setup monorepo | structure, Makefile, docker-compose (Postgres + pgvector), ruff, pytest, CI verte |
| 1 | Données | `make data` : téléchargement, Parquet, filtre adulte, rapport qualité |
| 2 | Transformations Spark | `drop_curve`, `critical_episode`, `retention_by_*`, catalogue anime chargés dans Postgres |
| 3 | Modèle de drop | 3 modèles comparés, `drop_metrics.json`, figures, artefact |
| 4 | Recommandation ALS | baseline vs ALS, métriques de classement, facteurs exportés, fold-in testé |
| 5 | API data | FastAPI dockerisée : `/media`, `/trending`, recos et risque de drop en mode démo (profil passé en paramètre) |
| 6 | Airflow | les 2 DAG tournent dans docker-compose, 1re exécution réussie |
| **—** | **Version minimale montrable** | pipeline + modèles + API ; Royston peut déjà l'ajouter au CV |
| 7 | Comptes et listes | auth, RGPD, `/me/list`, migrations Alembic, tests |
| 8 | Front, partie 1 | accueil, auth, onboarding, ma liste |
| 9 | Front, partie 2 | fiche œuvre (risque de drop, courbe), page « Pour toi », profil public |
| 10 | Recos contenu | embeddings pgvector, recos manga/manhwa et cross-média |
| 11 | Déploiement | appli en ligne, CI/CD, secrets gérés, monitoring de base |
| 12 | PWA | appli installable sur Android et iPhone depuis le navigateur, consultation de « Ma liste » hors ligne, page d'aide à l'installation (§ 8.1) |
| 13 | Power BI | vues SQL, `GUIDE.md`, `measures.dax` ; Royston construit le .pbix |
| 14 | Assistant IA | explication des recos en langage naturel + RAG sur la doc du projet ; fournisseur de LLM configurable par variable d'environnement, choisi par Royston à cette phase |
| 15 | README final | pitch, captures, schéma, résultats réels, choix techniques, limites, relance |

## 11. Tableau de bord Power BI (phase 13)
1. Vue d'ensemble : taux de drop global, top des animes les plus lâchés et les plus « tenus »
2. Courbes de drop : sélection d'un anime → épisode critique
3. Studios et genres : rétention par studio, Isekai vs Shonen vs autres
4. Saison en cours : évolution quotidienne (Jikan)
5. Modèles : métriques du modèle de drop et de l'ALS
6. Activité Tsuzuku : inscriptions, œuvres les plus ajoutées, drops déclarés (données agrégées et anonymes)

## 12. Contraintes et pièges connus
- Dataset anime arrêté en 2020 : les œuvres récentes viennent de Jikan et AniList, sans historique d'interactions.
- Pas d'historique massif d'interactions manga/manhwa : recos contenu, risque de drop indisponible au début.
- PySpark sous Windows : utiliser WSL2. Power BI Desktop : Windows uniquement.
- Spark local : `spark.driver.memory` réglé dans `settings.yaml` ; l'ALS sur le jeu complet peut dépasser la RAM → filtrage et échantillonnage.
- Jikan et AniList peuvent renvoyer 429/5xx : retries, logs, idempotence.
- Ne jamais commiter `data/`, `models/`, `.env`, `kaggle.json`, `node_modules/`.

## 13. Définition de « terminé » pour le CV
- Dépôt public, README complet, CI verte, relance documentée (`docker compose up` + `make`).
- Pour la version en ligne : URL publique qui répond.
- Tous les chiffres du README proviennent de `reports/` ou des sorties Spark.
- Royston sait expliquer chaque phase (`docs/LEARNING.md`).
