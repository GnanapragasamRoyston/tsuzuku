# ADR 005 — Recommandation ALS : données, protocole d'évaluation, fold-in, export

**Date** : 2026-11-17 · **Statut** : accepté (choix validés par Royston)

## Contexte
Tsuzuku recommande des animes à partir de la liste d'un utilisateur. Le modèle est un filtrage
collaboratif par factorisation matricielle (ALS de Spark MLlib), entraîné sur les notes
MyAnimeList. Contrainte forte : un utilisateur Tsuzuku **n'est jamais dans les données
d'entraînement**. Il faut donc calculer son vecteur à la volée (« fold-in ») dans l'API (phase 5),
sans Spark, à partir de quelques titres aimés. L'évaluation doit mesurer ce chemin-là, pas un
chemin plus confortable.

Données de départ : 56 726 861 notes (table `clean/rating_complete`), moyenne 7,53, médiane de
112 notes par utilisateur et de 230 notes par anime (source :
`reports/exploration_2026-11-16.json`, mesure `reco_ratings_profile`).

## Décisions

### Données : filtre d'activité itératif (20 / 50)
- On garde les utilisateurs avec **≥ 20 notes** et les animes avec **≥ 50 notes**
  (`config/settings.yaml`, section `reco`). En dessous, un facteur latent serait du bruit.
- Le filtre est **itératif** : retirer un anime peu noté peut faire passer un utilisateur sous
  son seuil, et inversement. On répète jusqu'à stabilité.
- Mesure : une seule passe gardait 56 273 090 notes, 264 537 utilisateurs et 10 861 animes
  (`reports/exploration_2026-11-16.json`). Le filtre itératif converge en **3 passes** vers
  **56 272 898 notes, 264 532 utilisateurs et 10 859 animes** (`reports/reco_metrics.json`, clé
  `data`). Le filtre retire donc très peu de notes.

### Split par utilisateur 80 / 10 / 10
| Lot | Utilisateurs | Notes | Notes masquées |
|---|---|---|---|
| train | 211 469 | 44 977 456 | 0 |
| validation | 26 501 | 5 649 392 | 1 127 948 |
| test | 26 562 | 5 646 050 | 1 129 026 |

Source : `reports/reco_metrics.json`, clé `data.splits`. Le tirage se fait par hachage de
l'identifiant utilisateur (reproductible, indépendant du partitionnement Spark).

### Les utilisateurs de validation et de test ne sont JAMAIS vus par l'ALS
C'est le choix central. L'ALS n'est entraîné que sur le train. Pour chaque utilisateur de
validation ou de test :
- **80 % de ses notes sont visibles**, 20 % sont **masquées** (`mask_fraction: 0.2`) ;
- son vecteur est calculé par **fold-in** à partir des notes visibles ;
- le modèle classe tout le catalogue sauf les animes visibles ;
- on regarde si les animes masqués qu'il a aimés remontent dans le top-K.

C'est exactement le **chemin de production** : un nouvel utilisateur Tsuzuku donne des titres,
l'API calcule son vecteur, puis classe. Les métriques mesurent donc ce que l'appli fera vraiment.

### Pertinent = note ≥ 8
Un anime masqué est « aimé » si sa note est ≥ 8 (`relevant_min_score`). La moyenne des notes est
7,53 et 54 % des notes sont ≥ 8 (`config/settings.yaml` ; distribution dans
`reports/exploration_2026-11-16.json`, `score_hist`). Un seuil plus bas rendrait pertinente une
large majorité des notes, y compris des titres seulement « corrects ». Un utilisateur sans aucun anime masqué pertinent n'est pas classé (116 sur le test,
26 446 classés ; `reports/reco_metrics.json`, `test.*.users_without_relevant` / `users_ranked`).

### Baseline : popularité
Score d'un anime = **nombre de notes ≥ 8 dans le train**. Tout le monde reçoit la même liste
(moins ses animes déjà vus). C'est le plancher à battre : sur ce type de données, la popularité
est une baseline solide.

### ALS explicite contre ALS implicite — choix validé par Royston
Plutôt que de trancher sur le papier, on **compare les deux** et on sélectionne sur la
**NDCG@10 de validation** (on recommande une liste, on ne prédit pas une note).
- **Explicite** : le modèle prédit la note (1-10). Il n'apprend que sur les notes observées.
- **Implicite** (Hu, Koren, Volinsky 2008) : le rating donné à Spark est **note − 5**, avec
  `alpha = 1`. Une note au-dessus de 5 est une préférence positive, d'autant plus sûre que la
  note est haute. Une note sous 5 est une **préférence négative** (« vu, pas aimé ») : préférence
  0, mais avec une confiance proportionnelle à l'écart. Une note de 5 exactement a un poids nul.
  Les notes ≤ 5 représentent 10,7 % des notes (`config/settings.yaml`). Les animes non vus
  comptent comme « préférence 0, confiance faible ».

### Grille d'hyperparamètres
- 40 points : 2 variantes × `rank` ∈ {16, 32, 64, 128} × `regParam` ∈ {0,01 ; 0,03 ; 0,05 ; 0,1 ;
  0,2}, `maxIter = 10`.
- Pour le temps de calcul, la grille s'entraîne sur **25 % des utilisateurs du train** et
  s'évalue sur **5 000 utilisateurs de validation** (`grid_user_fraction`, `grid_eval_users`).
- Le meilleur point de **chaque variante** est ensuite **réentraîné sur tout le train**. Le choix
  final entre explicite et implicite se fait sur la validation complète. Le test est évalué une
  seule fois.

### Fold-in en NumPy, vérifié contre Spark
À facteurs des animes Y fixés, le vecteur x d'un utilisateur a une solution exacte : c'est une
demi-étape d'ALS pour lui seul. Formules (`pipeline/src/tsuzuku_pipeline/ml/reco/fold_in.py`) :
- **explicite** : x = (Σ y yᵀ + λ·n·I)⁻¹ Σ r·y, avec n = nombre de notes. Le terme **λ·n** est
  la convention de Spark (régularisation pondérée par le nombre de notes).
- **implicite** : x = (YᵀY + Σ c₁ y yᵀ + λ·n₊·I)⁻¹ Σ_{r>0} (1 + c₁)·y, avec r = note − 5,
  c₁ = α·|r| et n₊ = nombre de notes avec r > 0 (Hu et al., avec l'extension de Spark pour les
  notes négatives). **YᵀY** ne dépend pas de l'utilisateur : il est calculé une seule fois.

Un **test de parité** entraîne un petit ALS Spark et vérifie que le fold-in NumPy retrouve les
facteurs utilisateur de Spark, pour les deux variantes. Sans ce test, une convention différente
(par exemple λ au lieu de λ·n) donnerait des vecteurs faux sans aucune erreur visible.

Si le fold-in est impossible (aucun anime connu du modèle, ou aucune préférence positive en
implicite), on se rabat sur la popularité.

### Note par défaut d'onboarding : 8
À l'onboarding, l'utilisateur choisit des titres aimés sans les noter (SPEC § 6.2). Chaque choix
vaut **8** : c'est la note la plus fréquente (14 514 054 notes ;
`reports/exploration_2026-11-16.json`, `score_hist."8"`) et c'est le seuil « aimé ». Une vraie
note l'emporte toujours sur la note par défaut.

### Export pour le backend (phase 5)
Le backend n'a besoin que des facteurs des animes : ni JVM, ni pickle.
- `models/reco_item_factors.parquet` : un vecteur par anime (10 859 animes, rank 128).
- `models/reco_model.json` : la fiche. Elle contient le **sha256** du Parquet, un
  **`schema_version`** (1), `n_items`, les paramètres du fold-in, la liste de repli
  `popularity_fallback` (500 animes) et un cas de référence **`parity_check`**.
- Copie par run dans `models/runs/<run_id>/`, jamais écrasée.
- Le backend gardera **une copie de `fold_in.py`** (il ne dépend pas du paquet pipeline). Cette
  copie est vérifiée par `parity_check` : avec les 6 animes donnés, notés 8, elle doit renvoyer
  exactement le top 10 attendu.

## Limites connues
- **Pas de dates** dans le dataset : le masquage est aléatoire. On ne peut pas masquer « les
  dernières notes », ce qui serait plus proche de l'usage réel.
- **Seuil ≥ 50 notes par anime calculé avant le split** : les notes des utilisateurs de
  validation et de test comptent dans ce seuil. Effet marginal : il ne décide que de la présence
  d'un anime au catalogue, pas de ses facteurs.
- **Meilleur point au bord de la grille pour le rank** : les deux variantes retiennent
  `rank = 128`, le plus grand testé (`selection.*.on_grid_edge = true`). L'optimum n'est donc
  pas encadré. Un rank plus grand coûte plus cher (sur la grille, en implicite à `regParam`
  0,05 : 24,1 s à rank 64, 81,5 s à rank 128 ; clé `grid[].fit_seconds`) et grossit l'artefact.
  **Non exploré.**
- **`regParam` est encadré** : 0,05 est retenu, et ses voisins 0,03 et 0,1 font moins bien pour
  les deux variantes à rank 128. En implicite, l'écart est minime (NDCG@10 de validation 0,4848 /
  0,4852 / 0,4798, clé `grid`) et de l'ordre du bruit sur 5 000 utilisateurs : le `regParam`
  compte peu dans cette plage.
- **sha256 = intégrité, pas authenticité** : il prouve que le fichier n'a pas changé depuis
  l'écriture, pas qu'il vient bien de nous ni qu'il était correct.
- **Premier run** : la première grille (rank 16-64, `regParam` 0,05-0,2) avait son meilleur point
  au bord (rank 64, `regParam` 0,05) pour les deux variantes. La grille a été élargie
  (`config/settings.yaml`, commentaire de la section `reco`).
- **`git_sha` suffixé `-dirty`** dans la fiche : le run a tourné avant le commit de la phase 4.
  Le code exécuté est celui de ce commit (aucune modification de code entre le run et le
  commit, seulement la documentation) ; les prochains runs sur un dépôt propre auront un SHA exact.

## Alternatives écartées
- **Split par note** (un utilisateur à la fois dans le train et le test) : l'ALS connaîtrait déjà
  son vecteur. On mesurerait un cas qui n'existe pas en production.
- **Sélection sur la RMSE** : elle ne mesure que la note prédite sur les animes déjà vus, pas la
  qualité d'une liste. Les résultats ci-dessous le confirment.
- **Choisir explicite ou implicite sans mesurer** : écarté, on compare les deux.
- **Réentraîner l'ALS à chaque nouvel utilisateur** : trop lent et il faudrait Spark dans l'API.
  Le fold-in calcule son vecteur à facteurs d'animes fixés, en une résolution de système linéaire
  (rank × rank) ; les facteurs des animes ne bougent qu'au prochain `make reco`.
- **Charger le modèle Spark dans le backend** : impose une JVM dans l'image de l'API.
- **Une seule passe de filtre** : laisse des lignes sous les seuils.
- **Grille sur tout le train** : 40 entraînements complets, trop long en local.

## Résultats
**Date** : 2026-11-17 · Source : `reports/reco_metrics.json` (run
`1263a415-e570-4b02-9a74-1d330ba0fb77`), fiche modèle `models/reco_model.json`.

### Modèle retenu
**ALS implicite**, `rank = 128`, `regParam = 0,05`, `maxIter = 10`, `alpha = 1`. Sur la
validation complète, sa NDCG@10 est de 0,494, contre 0,212 pour l'ALS explicite et 0,192 pour la
popularité (`val.*.at_k."10".ndcg`).

### Métriques sur le test, K = 10 (26 446 utilisateurs classés)
| Modèle | Précision@10 | Rappel@10 | NDCG@10 | Couverture@10 |
|---|---|---|---|---|
| Popularité (baseline) | 0,164 | 0,091 | 0,193 | 0,006 |
| ALS explicite | 0,173 | 0,115 | 0,212 | 0,445 |
| ALS implicite (retenu) | 0,418 | 0,260 | 0,493 | 0,213 |

Source : `test.<modèle>.at_k."10"`. Couverture = part du catalogue recommandée au moins une fois.

### RMSE (ALS explicite seulement)
Sur les 1 129 026 notes masquées du test, prédictions bornées à 1-10 :
- moyenne de l'anime (lissée vers la moyenne globale) : **1,503** ;
- ALS explicite : **1,096**.

Source : `rmse_test.item_mean`, `rmse_test.als_explicit`. L'ALS implicite n'a pas de RMSE : il
ne prédit pas une note.

### Une bonne RMSE ne fait pas un bon classement
L'ALS explicite prédit nettement mieux les notes que la moyenne de l'anime, mais il classe à
peine mieux que la popularité (NDCG@10 de 0,212 contre 0,193). Raison : il n'apprend que sur les
animes **que les gens ont choisi de regarder**. Or recommander, c'est classer tout le catalogue,
donc surtout des animes que l'utilisateur n'a pas vus, où le modèle n'a jamais eu d'exemple. Il
peut y prédire des notes hautes pour des titres de niche (sa couverture est la plus large,
0,445). L'ALS implicite traite au contraire « pas vu » comme une information : il apprend ce que
l'utilisateur va regarder **et** aimer.

### Onboarding : peu de titres aimés, sans note
Régime d'usage réel. Mêmes utilisateurs de test, mêmes cibles masquées ; le modèle ne reçoit que
*n* animes aimés (tirés parmi les notes visibles ≥ 8), tous notés 8. Les utilisateurs qui ont
moins de *n* animes aimés visibles sont écartés.

| Animes aimés donnés | Utilisateurs (écartés) | Popularité | ALS explicite | ALS implicite |
|---|---|---|---|---|
| 3 | 26 547 (15) | 0,193 | 0,135 | 0,175 |
| 5 | 26 512 (50) | 0,193 | 0,171 | 0,214 |
| 10 | 26 236 (326) | 0,194 | 0,200 | 0,281 |
| 20 | 23 806 (2 756) | 0,203 | 0,210 | 0,363 |

Valeurs : NDCG@10. Source : `onboarding_test.<n>.users`, `.users_excluded`,
`.models.<modèle>.at_k."10".ndcg`.

Lecture : avec **3 titres**, l'ALS implicite fait **moins bien** que la popularité (0,175 contre
0,193). À partir de **5 titres**, il passe devant (0,214 contre 0,193), et l'écart grandit avec
le nombre de titres. Avec le profil complet (80 % des notes), il atteint 0,493.

### Conséquence produit — proposition à valider par Royston
Non validée à ce jour. Proposition :
- demander **au moins 5 titres** à l'onboarding (la SPEC § 8 en prévoit déjà 10, ce qui est
  cohérent : 0,281 à 10 titres) ;
- **en dessous de 5 titres, servir la popularité** plutôt que l'ALS.

### Exemple (clé `showcase`)
Profil fictif qui a aimé Naruto, Death Note, Fullmetal Alchemist: Brotherhood, Steins;Gate,
Sword Art Online et Shingeki no Kyojin (6 titres, notés 8). Top 10 du modèle retenu :
Fullmetal Alchemist, One Punch Man, Angel Beats!, Code Geass: Hangyaku no Lelouch, Tokyo Ghoul,
Code Geass: Hangyaku no Lelouch R2, No Game No Life, Shingeki no Kyojin Season 2, Sword Art
Online II, Hunter x Hunter (2011). **5 de ces 10 titres** sont aussi dans le top 10 de
popularité (`showcase.shared_with_popularity`) : avec 6 titres très populaires, la liste reste
proche de la popularité, ce qui est cohérent avec le tableau d'onboarding.

### Corrections issues de la revue de code
- **Évaluation « onboarding » ajoutée** : le protocole complet (80 % des notes visibles) ne
  disait rien du cas réel à 3-20 titres.
- **Grille élargie** après le premier run (meilleur point au bord), et drapeau `on_grid_edge`
  dans le rapport.
- **Contrat avec le backend** : `schema_version`, `n_items`, contrôles au chargement (forme des
  facteurs, identifiants en double, valeurs non finies) et `parity_check`.
- **Ordre d'écriture** : l'artefact est écrit avant le rapport, et le rapport de façon atomique.
  Un échec ne laisse jamais un rapport qui décrit un modèle absent.
- **Traçabilité** : `git_sha` et version de NumPy dans la fiche (PySpark 3.5.9, NumPy 2.4.6 ;
  `models/reco_model.json`, `versions`) ; test de déterminisme (même seed → mêmes facteurs).
- **Une seule règle de classement** : `top_k_positions` sert à l'évaluation et au service. Les
  ex æquo sont départagés de la même façon des deux côtés.
- **Baseline de la RMSE renommée `item_mean`** : c'est la moyenne de l'anime, pas la popularité
  (qui classe mais ne prédit pas de note).
- **Entrées du fold-in validées** : longueurs différentes, note non finie (NaN), anime en double
  ou note hors 1-10 lèvent une erreur.

### Suites non traitées
- **Intervalles de confiance** par bootstrap **par utilisateur** sur les métriques de test.
- **`rank` > 128** : la NDCG de validation monte encore entre 64 et 128.
- **Mélange ALS / popularité** pour les profils courts, au lieu d'une bascule nette à 5 titres.
