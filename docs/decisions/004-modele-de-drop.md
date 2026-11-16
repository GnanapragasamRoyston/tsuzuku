# ADR 004 — Modèle de drop : features, fuites interdites, protocole d'évaluation

**Date** : 2026-11-16 · **Statut** : accepté (choix validés par Royston)

## Contexte
Le « risque de drop » est un modèle de churn : pour un couple (utilisateur, anime), probabilité
que l'utilisateur lâche l'anime. Il sera servi par l'API (phase 5) pour des utilisateurs Tsuzuku,
qui n'ont que leur liste. Population : 71 M lignes Completed + Dropped, dont 5,91 % de drops
(mesuré sur `clean` le 2026-11-16 ; source : `reports/exploration_2026-11-16.json`,
mesure `phase3_population_profile`).

## Décisions

### Features autorisées (calculables depuis la liste d'un utilisateur Tsuzuku)
- **Œuvre** : format, épisodes, durée, source, année, rating d'âge, rang de popularité, studio
  principal (top-30 du train + « infrequent »), genres en multi-hot (41).
- **Utilisateur, en leave-one-out** (la ligne prédite n'y contribue jamais) : taille de liste,
  nb de Completed/Dropped, taux de drop historique, note moyenne donnée (notes > 0), part de
  chaque genre, **affinité de genre** (moyenne des parts de l'utilisateur sur les genres de
  l'œuvre ; ajout validé par Royston).

### Features interdites (fuite de la cible) — test bloquant
| Colonne | Pourquoi |
|---|---|
| `watched_episodes` | un drop a mécaniquement moins d'épisodes vus |
| `score` de la ligne | 54 % des drops ne sont pas notés contre 15 % des Completed : la présence d'une note révèle presque l'issue (source : `reports/exploration_2026-11-16.json`) |
| `dropped`, `completed`, `watching`, `on_hold`, `plan_to_watch`, `members`, `favorites`, `mal_score`, `ranked`, `score_1..10` | agrégats MAL qui comptent la ligne elle-même et décrivent l'issue globale |

`FORBIDDEN_COLUMNS` est vérifié par un test sur la liste des features **et** sur les colonnes
vues par le pipeline final. `prepare_x` ne transmet que les colonnes du contrat.

### Parité entraînement / production
Les features ont deux implémentations : Spark (entraînement, 71 M lignes) et Python pur (API).
Un test les compare valeur par valeur sur un même jeu. Le vocabulaire des genres est figé à
l'entraînement et enregistré dans la fiche modèle.

### Protocole
- Features Spark sur tout le jeu, puis échantillon de **3 % des utilisateurs** (toutes leurs
  lignes, tirage par hachage) pour scikit-learn.
- Split **par utilisateur** (`GroupShuffleSplit`) 70 / 15 / 15. Un utilisateur dans le train et
  le test laisserait le modèle « reconnaître » son profil.
- Validation : choix des hyperparamètres (PR-AUC), du modèle final et du seuil (F1 de la classe
  drop). Test : évalué une seule fois, rien n'y est réglé.
- **Pas de pondération des classes** : l'appli affiche une probabilité (« 72 % »), qui doit
  rester honnête. Le déséquilibre est traité par la métrique (PR-AUC) et le seuil. Calibration
  isotonique disponible (`calibration: isotonic`), sur une moitié de validation distincte de
  celle du seuil ; activée seulement si la courbe de calibration le justifie.
- Modèles : `DummyClassifier` (plancher), `LogisticRegression`, `HistGradientBoostingClassifier`.

### Limites connues
- **Pas de dates** dans le dataset : la liste d'un utilisateur contient aussi des œuvres vues
  après celle qu'on prédit (fuite temporelle impossible à corriger ici).
- Le rang de popularité est un agrégat MAL sur tous les utilisateurs ; autorisé par la SPEC car
  Jikan le fournit en production.
- `joblib` = pickle : on ne charge que nos propres artefacts (provenance dans la fiche modèle).

## Alternatives écartées
- `class_weight="balanced"` : améliore parfois le rappel, mais gonfle les probabilités.
- Split aléatoire par ligne : fuite par l'utilisateur, métriques trop optimistes.
- Sélection sur la ROC-AUC : trop flatteuse avec 6 % de positifs.
- Features calculées seulement sur l'échantillon : valeurs identiques (tirage par utilisateur),
  mais la SPEC demande le calcul sur tout le jeu ; la table complète resservira (phase 4).

## Résultats et suites
**Date** : 2026-11-16 · Source des métriques : `reports/drop_metrics.json` (run
`3e8b164f-1a69-4423-bf5d-df30210f0f99`), fiche modèle `models/drop_model.json`.

### Modèle retenu
`HistGradientBoostingClassifier`, choisi sur la **validation** : PR-AUC de 0,426, contre 0,370
pour la régression logistique et 0,065 pour la baseline. Le test n'a servi qu'à l'évaluation finale.

### Métriques sur le test (313 245 lignes, 1 437 utilisateurs, 5,60 % de drops)
| Modèle | PR-AUC | ROC-AUC | F1 drop | Brier | ECE |
|---|---|---|---|---|---|
| Baseline | 0,056 | 0,500 | 0,106 | 0,0529 | 0,0012 |
| Régression logistique | 0,361 | 0,869 | 0,396 | 0,0437 | 0,0065 |
| Gradient boosting (retenu) | 0,432 | 0,901 | 0,437 | 0,0404 | 0,0053 |

Au seuil choisi sur la validation (0,241), le modèle retenu a une précision de 0,395 et un rappel
de 0,489.

### Calibration : `none`
L'ECE du modèle retenu est de 0,0053 sur le test, sans correction. Dans le dernier décile, la
probabilité moyenne prédite est de 0,352 pour un taux observé de 0,332. La courbe ne justifie pas
la calibration isotonique : elle reste disponible mais n'est pas activée.

### Sources des chiffres cités plus haut
Les valeurs 5,91 %, 54 % et 15 % viennent de `reports/exploration_2026-11-16.json`, mesure
`phase3_population_profile` : `drop_share` ; `dropped_rows_unrated` / `dropped_rows` ;
`completed_rows_unrated` / (`completed_plus_dropped_rows` − `dropped_rows`). Ce sont des mesures
ponctuelles, non rejouées par `make`.

### Corrections issues de la revue de code
Aucun point critique ou grave. Corrections appliquées :
- **ECE d'un score constant** : la baseline prédit une seule probabilité ; l'ECE sortait fausse.
  Ce cas est maintenant traité comme un bin unique.
- **Parité pour les œuvres hors catalogue** : le test de parité Spark / Python couvre ce cas.
- **Artefact archivé par run** : `models/runs/<run_id>/`, avec un sha256 enregistré dans la fiche
  modèle et vérifié avant chargement (`joblib` = pickle).
- **Nombre réel d'itérations** enregistré dans la fiche modèle (`n_iter_effective`).

### Suite non traitée
Intervalles de confiance sur la PR-AUC test par bootstrap **par utilisateur** (rééchantillonner
des utilisateurs, pas des lignes, pour respecter la dépendance entre lignes d'un même utilisateur).
