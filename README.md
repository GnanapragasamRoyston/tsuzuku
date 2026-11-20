# Tsuzuku 続く

> Suivi d'animes, mangas et manhwas qui recommande quoi regarder — et **prévient avant que tu décroches**.

Sous le capot : un pipeline Big Data sur 109 M d'interactions MyAnimeList (PySpark), une ingestion
quotidienne (Airflow), un modèle de churn (« risque de drop », scikit-learn), une recommandation
ALS (Spark MLlib), une API FastAPI et un front Next.js.

🚧 **En construction** — phase 5 terminée (API data). Voir [docs/SPEC.md](docs/SPEC.md) pour le
cahier des charges et [docs/architecture.md](docs/architecture.md) pour l'architecture.

## Démarrage

Prérequis : WSL2 (ou Linux/macOS), Docker, `make`, [uv](https://docs.astral.sh/uv/), Java 17
(PySpark), un jeton Kaggle dans `~/.kaggle/access_token` (`chmod 600`).

```bash
make setup     # environnements Python + .env
make up        # Postgres 16 + pgvector
make db-check  # vérifie l'extension et les schémas
make data      # Kaggle → Parquet (staging/clean), filtre adulte, rapport qualité, échantillon
make spark     # marts (courbes de drop, épisode critique, rétention) + catalogue → Postgres
make train     # modèle de drop : features Spark, 3 modèles scikit-learn, métriques, figures, artefact
make reco      # recommandation : popularité vs ALS explicite/implicite (Spark MLlib), fold-in, facteurs exportés
make api       # API FastAPI en local, rechargement auto (http://localhost:8000/docs)
make api-up    # API dans Docker (profil compose « api »)
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
| `infra/` | scripts d'init Postgres |
| `docs/` | spec, architecture, décisions (ADR), journal d'apprentissage |

## Données

Dataset « Anime Recommendation Database 2020 » (Kaggle `hernan4444/anime-recommendation-database-2020`,
licence **CC0-1.0**), collecté sur MyAnimeList début 2020. Données fraîches via l'API Jikan et l'API
GraphQL AniList (phase 6).

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

## API (phase 5)

API FastAPI qui sert le catalogue, la saison en cours, les recommandations et le risque de drop.
**Mode démo** : le profil de l'utilisateur est passé dans la requête ; les comptes arrivent en
phase 7.

Lancement : `make up` (base), puis `make api-up` (API dans Docker) ou `make api` (en local). Il
faut les artefacts de `make train` et `make reco` dans `models/`. Documentation interactive
(Swagger) : http://localhost:8000/docs

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/health` | vivacité : toujours 200, `status` à `degraded` si la base ou un modèle manque |
| GET | `/health/ready` | disponibilité : 503 si la base ou un modèle manque |
| GET | `/media/search?q=…` | recherche par titre (filtre `kind` facultatif) |
| GET | `/media/{media_id}` | fiche d'une œuvre : genres, épisode critique, courbe de drop |
| GET | `/trending` | saison en cours (Jikan), reliée au catalogue quand l'anime y figure |
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
