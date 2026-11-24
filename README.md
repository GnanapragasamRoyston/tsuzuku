# Tsuzuku 続く

> Suivi d'animes, mangas et manhwas qui recommande quoi regarder — et **prévient avant que tu décroches**.

Sous le capot : un pipeline Big Data sur 109 M d'interactions MyAnimeList (PySpark), une ingestion
quotidienne (Airflow), un modèle de churn (« risque de drop », scikit-learn), une recommandation
ALS (Spark MLlib), des recos par le contenu (embeddings, pgvector), une API FastAPI et un front
Next.js.

**En ligne : [tsuzuku-eight.vercel.app](https://tsuzuku-eight.vercel.app)** — front sur Vercel, API sur Google Cloud
Run, base Neon (Francfort). Le premier chargement après une période sans visite prend environ
5 s (l'API et la base se réveillent : 0 € au repos).

🚧 **En construction** — phases 0 à 11 terminées (pipeline, modèles, API, appli, recos par le
contenu, mise en ligne). Voir [docs/SPEC.md](docs/SPEC.md) pour le cahier des charges et
[docs/architecture.md](docs/architecture.md) pour l'architecture.

## Démarrage

Prérequis : WSL2 (ou Linux/macOS), Docker, `make`, [uv](https://docs.astral.sh/uv/), Java 17
(PySpark), Node 24 LTS (front), un jeton Kaggle dans `~/.kaggle/access_token` (`chmod 600`).

```bash
make setup     # environnements Python + .env
make up        # Postgres 16 + pgvector
make db-check  # vérifie l'extension et les schémas
make data      # Kaggle → Parquet (staging/clean), filtre adulte, rapport qualité, échantillon
make spark     # marts (courbes de drop, épisode critique, rétention) + catalogue → Postgres
make train     # modèle de drop : features Spark, 3 modèles scikit-learn, métriques, figures, artefact
make reco      # recommandation : popularité vs ALS explicite/implicite (Spark MLlib), fold-in, facteurs exportés
make api-keys  # secret des sessions (JWT_SECRET) ajouté à .env (jamais affiché)
make migrate   # migrations Alembic du schéma app (comptes, listes)
make api       # API FastAPI en local, rechargement auto (http://localhost:8000/docs)
make api-up    # API dans Docker (profil compose « api », migrations appliquées avant)
make airflow-keys  # secrets d'Airflow ajoutés à .env (jamais affichés)
make airflow-up    # Airflow dans Docker (http://localhost:8080)
make airflow-trigger DAG=anilist_catalog_sync  # lance un DAG tout de suite
make covers    # couvertures manquantes des animes, depuis AniList (aussi fait par le DAG hebdo)
make web       # front Next.js en local (http://localhost:3000), avec make api lancé à côté
make web-test  # lint, types et tests Vitest du front
make web-e2e   # parcours de bout en bout (Playwright + axe) sur une base de test dédiée
make figures   # chiffres clés de toutes les phases → reports/key_figures.{json,md} (sans recalcul)
make lint test # qualité
make help      # toutes les commandes
```

## Structure

| Dossier | Contenu |
|---|---|
| `pipeline/` | Data/ML : Spark, Airflow, entraînement |
| `backend/` | API FastAPI |
| `packages/` | code ML partagé pipeline ↔ API (`tsuzuku-ml` : fold-in, features de drop, artefacts) |
| `frontend/` | Next.js (phase 8) |
| `config/` | `settings.yaml` (seeds, seuils, chemins), `watchlist.yaml` |
| `infra/` | scripts d'init Postgres, image Airflow |
| `docs/` | spec, architecture, décisions (ADR), journal d'apprentissage |

## Données

Dataset « Anime Recommendation Database 2020 » (Kaggle `hernan4444/anime-recommendation-database-2020`,
licence **CC0-1.0**), collecté sur MyAnimeList début 2020. Données fraîches via l'API Jikan
(statistiques quotidiennes de la saison en cours) et l'API GraphQL AniList (catalogue manga, manhwa
et manhua), ingérées par Airflow (phase 6, voir [Ingestion](#ingestion-phase-6)).

- Dictionnaire, couches et règles de nettoyage : [docs/data.md](docs/data.md)
- Volumes et qualité, générés par `make data` : [reports/data_quality.md](reports/data_quality.md)
- Contenus adultes exclus partout (`Rating` en `Rx` ou genre `Hentai`) : [ADR 002](docs/decisions/002-donnees-brutes-parquet.md)

## Définitions (indicateurs de drop)

Calculés par `make spark` sur les lignes **Completed** et **Dropped** (issue connue) ; détails et
choix dans l'[ADR 003](docs/decisions/003-marts-drop-et-chargement-postgres.md). Seuils dans
`config/settings.yaml`.

| Indicateur | Définition |
|---|---|
| taux de drop | dropped / (dropped + completed) |
| taux de complétion | completed / commencés (watching + completed + on hold + dropped) |
| progression au drop | épisodes vus / épisodes de l'anime (si connu) |
| courbe de drop | nombre de drops par épisode atteint et part cumulée ; l'épisode 0 = lâché avant de commencer |
| épisode critique | épisode ≥ 1 qui concentre le plus de drops (animes ≥ 3 épisodes et ≥ 50 drops après le début) |
| risque de départ | part de ceux qui lâchent parmi ceux qui ont commencé (épisode 1) |
| point de non-retour | 1er épisode à partir duquel le risque de lâcher est **divisé par 4** par rapport au départ |

Limites : les spectateurs encore en cours sont ignorés (censure à droite) ; MAL sous-déclare les
drops par rapport aux Completed, d'où la définition relative du point de non-retour.
Volumes produits : [reports/marts_summary.json](reports/marts_summary.json).

## API (phases 5 et 7)

API FastAPI qui sert le catalogue, la saison en cours, les comptes et les listes, les
recommandations et le risque de drop. Le **mode démo** (profil passé dans la requête) reste
disponible sans compte.

Lancement : `make up` (base), `make spark` (catalogue, requis par les migrations),
`make api-keys` (une fois), puis `make api-up` (API dans Docker, migrations comprises) ou
`make migrate && make api` (en local). Il faut les artefacts de
`make train` et `make reco` dans `models/`. Documentation interactive (Swagger) :
http://localhost:8000/docs

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/health` | vivacité : toujours 200, `status` à `degraded` si la base ou un modèle manque |
| GET | `/health/ready` | disponibilité : 503 si la base ou un modèle manque |
| GET | `/media/search?q=…` | recherche par titre (filtre `kind` facultatif) |
| GET | `/media/{media_id}` | fiche d'une œuvre : genres, épisode critique, courbe de drop |
| GET | `/trending` | saison en cours (snapshot Jikan du jour en base, depuis la phase 6), reliée au catalogue |
| POST | `/demo/recommendations` | recommandations à partir de titres aimés |
| POST | `/demo/drop-risk` | risque de drop d'une œuvre à partir de la liste de l'utilisateur |

```bash
curl "http://localhost:8000/media/search?q=death%20note&kind=anime"

# media_id = identifiant interne (catalog.media.id), pas le MAL_ID. Ceux-ci (Death Note, Naruto,
# Steins;Gate, Shingeki no Kyojin, Sword Art Online, FMA: Brotherhood) sont ceux de la base de dev
# du 2026-11-20 ; ailleurs, les relire avec /media/search.
curl -X POST http://localhost:8000/demo/recommendations \
  -H "Content-Type: application/json" \
  -d '{"liked": [{"media_id": 1337}, {"media_id": 11}, {"media_id": 4954, "score": 10},
                 {"media_id": 6551}, {"media_id": 5788}, {"media_id": 3447}], "k": 10}'
```

La réponse indique la stratégie suivie (`als` ou `popularity`) et pourquoi. Règle : sous 5 animes
**aimés** (note ≥ 8, ou choisis sans note) connus du modèle, l'API sert la popularité, car avec
3 titres l'ALS fait moins bien qu'elle ([ADR 006](docs/decisions/006-api-data.md)). Un manga, un
manhwa ou un anime plus récent que les données d'entraînement reçoit `insufficient_data` au lieu
d'un risque de drop chiffré.

### Comptes et listes (phase 7)

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/logout` | inscription, connexion (cookie de session), déconnexion de toutes les sessions |
| GET / PATCH / DELETE | `/me` | profil ; réglage du profil public (opt-in, phase 9) ; suppression du compte et de ses données (mot de passe demandé) |
| GET | `/me/export` | export RGPD en JSON (profil, liste, onboarding) |
| GET | `/me/list?status=&limit=&offset=` | ma liste, par statut, paginée |
| GET | `/me/list/{media_id}` | une seule entrée (fiche œuvre), 404 si absente |
| POST / PUT / DELETE | `/me/list/{media_id}` | ajouter (POST : jamais d'écrasement) ou modifier une œuvre (statut, progression, « lâché à l'épisode X », note, critique, dates) ; la retirer |
| POST | `/me/onboarding` | au moins 10 œuvres aimées |
| GET | `/me/recommendations?kind=anime` | recos depuis l'onboarding et la liste : ALS pour les animes ; `kind=manga`, `manhwa`, `manhua` (un ou plusieurs) : recos par le contenu (phase 10), profil tiré de toute la liste |
| GET | `/me/drop-risk/{media_id}` | risque de drop depuis ma liste |
| GET | `/media/{id}/similar?k=` | « Dans le même esprit » : voisins par le contenu, tous types (phase 10) |
| POST | `/media/{id}/cover-suggestions` | proposer une jaquette (URL d'un domaine autorisé, modération) |
| GET | `/users/{pseudo}` | profil public (phase 9) : chiffres, genres favoris, dernières notes ; même 404 pour un profil privé ou inconnu |

Sécurité ([ADR 008](docs/decisions/008-comptes-et-listes.md)) : mots de passe hachés en argon2id,
session JWT dans un cookie `httpOnly` + `Secure` + `SameSite=Lax`, révoquée à la déconnexion,
connexion limitée après 5 échecs, aucun email ni mot de passe dans les journaux. Les tables du
schéma `app` sont créées par des migrations Alembic ; `catalog` et `mart` restent au pipeline.
Données et droits : [docs/privacy.md](docs/privacy.md).

## Front (phases 8 et 9)

Next.js 16 (App Router, TypeScript), Tailwind v4, TanStack Query. Direction visuelle « Journal
de bord » : [docs/DESIGN.md](docs/DESIGN.md) (tokens, composants, ton, contrastes vérifiés).
Choix techniques : [ADR 009](docs/decisions/009-front-next.md).

| Page | Rôle |
|---|---|
| `/` | accueil : populaires, mangas et manhwas, un chiffre de drop réel en affiche, saison en cours |
| `/inscription`, `/connexion` | comptes (cookie de session posé par l'API, jamais visible du JavaScript) |
| `/onboarding` | choisir au moins 10 œuvres aimées (onglets, recherche) |
| `/ma-liste` | onglets par statut, « +1 ép. », « J'ai lâché », passage en « Terminé » au dernier épisode ; recos « Pour toi » à côté |
| `/oeuvre/{id}` | fiche (phase 9) : risque de drop personnel, courbe de drop par épisode avec épisode critique et point de non-retour, communauté, note sur 10 |
| `/pour-toi` | recos en page entière (phase 9) : une à la une, puis une rangée ; manga et manhwa en phase 10 |
| `/profil/{pseudo}` | profil public (phase 9), privé par défaut : épisodes vus, taux de drop, genres favoris, dernières notes |
| `/compte`, `/confidentialite` | déconnexion, profil public, export, suppression du compte ; données et droits |

Lancement local : `make up`, `make api`, puis `make web` (http://localhost:3000). Le navigateur
ne parle qu'au front, qui relaie `/api/*` vers l'API (même origine : pas de CORS, cookie toujours
envoyé). Le code ne peut pas s'écarter de DESIGN.md : les valeurs par défaut de Tailwind sont
supprimées, et un test refuse toute couleur, police ou valeur en dur, et recalcule les contrastes.

Tests : `make web-test` (Vitest : logique et garde-fous du design) et `make web-e2e`
(Playwright, sur une base de test et la vraie API : inscription → onboarding → recos → ajout →
+1 épisode → fiche et note → profil public → Pour toi, avec axe-core et un contrôle de débordement à
375 et 1440 px). Choix de la phase 9 : [ADR 011](docs/decisions/011-front-partie-2.md).

Couvertures : le dataset 2020 n'a pas d'images. `make covers` (et le DAG AniList chaque semaine)
les récupère sur AniList par identifiant MAL, dans la plus grande taille proposée ; les
œuvres sans image ont une jaquette de secours composée (palette « jaquette » de DESIGN.md).
Couverture par type, source et popularité : `make covers-report` →
`reports/covers_coverage.json`. Titres : le titre anglais d'abord (« Solo Leveling »), le romaji
reste cherchable. Choix : [ADR 012](docs/decisions/012-qualite-des-jaquettes.md).

« Proposer une jaquette » (fiche œuvre) : une URL d'image d'AniList, MyAnimeList ou Kitsu, mise en
file de modération ; rien ne s'affiche avant validation (`make covers-review`,
`make covers-approve ID=…`, `make covers-reject ID=…`). L'API ne télécharge jamais l'URL.

## Production (phase 11)

| Brique | Service |
|---|---|
| Front | Vercel (fonctions à Francfort) |
| API, migrations, ingestion planifiée | Google Cloud Run (service + jobs), Cloud Scheduler, Francfort |
| Base | Neon, Postgres 16 + pgvector, Francfort |
| Modèles servis | Cloud Storage (bucket privé), copiés au démarrage de l'API |

- Déploiement à chaque CI verte sur `main` (`.github/workflows/deploy.yml`) : images, **migration
  avant l'API**, API, jobs d'ingestion, test de fumée. GitHub → Google Cloud sans clé (Workload
  Identity Federation).
- L'API refuse tout appel qui ne vient pas du front (secret partagé, 403) ; la limite de
  connexion compte par visiteur, avec l'IP transmise par le relais (vérifié en production).
- Démarrage de l'API mesuré dans les journaux de Cloud Run : 2,9 à 3,5 s, dont 1,4 à 1,9 s de
  copie des modèles.
- Surveillance : sonde `/health/ready` toutes les 15 min avec alerte e-mail, alerte de budget à 5 €.

Mise en place et dépannage : [docs/deploy.md](docs/deploy.md) ; choix :
[ADR 014](docs/decisions/014-deploiement.md).

## Ingestion (phase 6)

Deux DAG Airflow (2.11, dans Docker) gardent le catalogue à jour. Le code métier vit dans
`pipeline/src/tsuzuku_pipeline/ingestion/` et se teste sans Airflow ; les DAG ne font
qu'enchaîner les tâches.

Lancement : `make up` (base), `make airflow-keys` (une seule fois : clés et mot de passe admin
aléatoires écrits dans `.env`, jamais affichés), puis `make airflow-up`. Interface :
http://localhost:8080, identifiants `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` dans `.env`.
Lancer un DAG sans attendre son planning : `make airflow-trigger DAG=anilist_catalog_sync`.

| DAG | Planning | Tâches | Sortie |
|---|---|---|---|
| `jikan_daily_ingest` | tous les jours, 06:00 UTC | `collect` → `fetch_stats` → `load` → `quality_check` | stats MAL de la saison en cours + watchlist → `catalog.media_daily_stats` |
| `anilist_catalog_sync` | le lundi, 05:00 UTC | `fetch_pages` → `load` → `quality_check` | 5 000 titres les plus populaires (manga, manhwa, manhua) → `catalog.media`, genres, tags |

Principes : réponses brutes écrites d'abord dans `data/raw/<source>/<date>/` (une tâche se relance
seule, sans rappeler l'API) ; upserts idempotents (relancer ne crée aucun doublon) ; limites de
débit respectées (1 requête/s pour Jikan, 2,1 s entre deux appels AniList, retries avec
`Retry-After`) ; contrôle qualité et rapport JSON à chaque exécution (`reports/ingestion/`) ; les
colonnes du dataset 2020 utilisées par le modèle de drop ne sont jamais modifiées.

**AniList, exécuté pour de vrai** (source : `reports/exploration_2026-11-20.json`, mesure
`anilist_first_runs`) : 5 000 titres récupérés en 100 pages (3,5 minutes pour la récupération à
la 1re exécution). Catalogue final : 3 715 mangas, 1 103 manhwas et 182 manhuas, avec 344 tags
(36 233 liens œuvre-tag). Une relance sur le même intervalle a donné 0 insertion et 5 000 mises à
jour : l'upsert est bien idempotent.

**Jikan** était injoignable pendant toute la phase (aussi hors de la machine) : lors de sa 1re
exécution, la tâche `collect` a échoué à ses 2 premiers essais par timeout (mesure
`jikan_first_run`). Le DAG est testé avec des réponses simulées ; sa
1re exécution réelle reste à faire au retour de Jikan.

`/trending` lit désormais le snapshot du DAG en base (`catalog.media_daily_stats`, animes de la
saison). L'appel direct à Jikan ne sert plus qu'en repli, si le snapshot manque ou a plus de
2 jours (`api.trending_max_age_days`).

Choix et limites : [ADR 007](docs/decisions/007-airflow-ingestion.md).

## Résultats

Tous les chiffres viennent de fichiers générés dans `reports/`.

### Modèle de drop (phase 3)

Cible : un couple (utilisateur, anime) Completed ou Dropped est-il un drop ? Population : 71 M
lignes, dont 5,91 % de drops. Les features sont calculées par Spark sur tout le jeu, puis
scikit-learn s'entraîne sur 3 % des utilisateurs (9 576 utilisateurs, 2 114 716 lignes). Split par
utilisateur 70 / 15 / 15 ; hyperparamètres, modèle final et seuil choisis sur la validation ; test
évalué une seule fois (313 245 lignes, 5,60 % de drops).

| Modèle (test) | PR-AUC | ROC-AUC | F1 drop | Précision | Rappel | Brier | ECE |
|---|---|---|---|---|---|---|---|
| `DummyClassifier` (plancher) | 0,056 | 0,500 | 0,106 | 0,056 | 1,000 | 0,0529 | 0,0012 |
| `LogisticRegression` | 0,361 | 0,869 | 0,396 | 0,347 | 0,462 | 0,0437 | 0,0065 |
| `HistGradientBoostingClassifier` (retenu) | 0,432 | 0,901 | 0,437 | 0,395 | 0,489 | 0,0404 | 0,0053 |

F1, précision et rappel sont donnés au seuil choisi sur la validation (0,241 pour le modèle retenu).

Calibration : sans pondération des classes ni correction, l'ECE du modèle retenu est de 0,0053 ;
la calibration isotonique, disponible, n'a donc pas été activée.

Variables les plus importantes (importance par permutation, en perte de PR-AUC sur le test) :

| Variable | Importance |
|---|---|
| `user_drop_rate` (taux de drop historique de l'utilisateur, hors ligne prédite) | 0,301 |
| `episodes` (nombre d'épisodes) | 0,215 |
| `popularity` (rang de popularité) | 0,124 |
| `start_year` (année) | 0,089 |

Cette mesure indique quelles variables comptent, pas le sens de leur effet. Les variables corrélées
entre elles (parts de genre) voient leur importance individuelle sous-estimée.

- Métriques complètes : [reports/drop_metrics.json](reports/drop_metrics.json)
- Figures : [roc.png](reports/figures/roc.png), [pr.png](reports/figures/pr.png),
  [calibration.png](reports/figures/calibration.png), [importance.png](reports/figures/importance.png)
- Chiffres clés de toutes les phases : [reports/key_figures.md](reports/key_figures.md)
- Choix et limites : [ADR 004](docs/decisions/004-modele-de-drop.md)

### Recommandation ALS (phase 4)

Données : 56 272 898 notes de 264 532 utilisateurs sur 10 859 animes, après un filtre d'activité
itératif (utilisateurs ≥ 20 notes, animes ≥ 50 notes). Split par utilisateur 80 / 10 / 10. Les
utilisateurs de validation et de test ne sont **jamais vus par l'ALS** : leur vecteur est calculé
par *fold-in* (moindres carrés en NumPy) sur 80 % de leurs notes, et on cherche à retrouver les
20 % masquées. C'est le chemin de production pour un nouvel utilisateur. Un anime masqué est
pertinent si sa note est ≥ 8. Trois modèles : popularité (nombre de notes ≥ 8 dans le train), ALS
explicite, ALS implicite (note − 5 comme signal). Hyperparamètres et modèle final choisis sur la
NDCG@10 de validation ; test évalué une seule fois (26 446 utilisateurs classés).

| Modèle (test, K = 10) | Précision@10 | Rappel@10 | NDCG@10 | Couverture@10 |
|---|---|---|---|---|
| Popularité (baseline) | 0,164 | 0,091 | 0,193 | 0,006 |
| ALS explicite (rank 128, regParam 0,05) | 0,173 | 0,115 | 0,212 | 0,445 |
| ALS implicite (rank 128, regParam 0,05) (retenu) | 0,418 | 0,260 | 0,493 | 0,213 |

Couverture : part du catalogue recommandée au moins une fois.

RMSE sur les 1 129 026 notes masquées du test (prédictions bornées à 1-10) : 1,096 pour l'ALS
explicite, contre 1,503 pour la moyenne de l'anime. L'ALS implicite ne prédit pas de note.

Onboarding : le modèle ne reçoit que *n* animes aimés, sans note (note par défaut : 8). Mêmes
utilisateurs de test, mêmes cibles. NDCG@10 :

| Animes aimés donnés | Utilisateurs | Popularité | ALS explicite | ALS implicite |
|---|---|---|---|---|
| 3 | 26 547 | 0,193 | 0,135 | 0,175 |
| 5 | 26 512 | 0,193 | 0,171 | 0,214 |
| 10 | 26 236 | 0,194 | 0,200 | 0,281 |
| 20 | 23 806 | 0,203 | 0,210 | 0,363 |

L'ALS explicite prédit mieux les notes que la moyenne de l'anime, mais classe à peine mieux que
la popularité : une bonne RMSE ne fait pas une bonne liste. L'ALS implicite, lui, bat nettement
la popularité, à condition d'avoir assez de signal : avec 3 titres il fait moins bien qu'elle, à
partir de 5 il passe devant. Limite : le meilleur `rank` (128) est au bord de la grille, un rank
plus grand n'a pas été exploré.

- Métriques complètes : [reports/reco_metrics.json](reports/reco_metrics.json)
- Figures : [reco_grid.png](reports/figures/reco_grid.png),
  [reco_ndcg_at_k.png](reports/figures/reco_ndcg_at_k.png),
  [reco_recall_at_k.png](reports/figures/reco_recall_at_k.png),
  [reco_onboarding.png](reports/figures/reco_onboarding.png)
- Chiffres clés de toutes les phases : [reports/key_figures.md](reports/key_figures.md)
- Choix et limites : [ADR 005](docs/decisions/005-recommandation-als.md)
